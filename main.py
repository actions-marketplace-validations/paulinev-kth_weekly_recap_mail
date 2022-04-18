"""
Module to automaticly send an email to all students with at least one register task with 
    - the week planning 
    - the week schedule 
    - a summary of the student's task (task registered and next task deadline)

These informations are found thanks to :
    - analyze of the readme (week date, week planning, task deadlines)
    - analyze of the statistics issue that summarize the task per student
    - analyze of the course calendar 
"""

import requests
import base64,os
import icalendar
import datetime
import pytz
import re
import smtplib, ssl
import logging

logging.basicConfig(filename="automatic_mail.log",
                    format='%(asctime)s %(message)s',
                    filemode='w')

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

github_repo_name = 'KTH/devops-course'
github_name = "KTH/devops-course"
readme_url = "https://api.github.com/repos/KTH/devops-course/contents/README.md"
readme_url_va = f"https://api.github.com/repos/{github_repo_name}/contents/README.md"
calendar_url = "https://www.kth.se/social/course/DD2482/calendar/ical/?lang=en"
search_url = f"https://api.github.com/search/issues?q=statistics+in:title%20repo:{github_repo_name}"



######################
### README analyze ###
######################

def get_readme_info() :
    """
    Download course README
    Return list of paragraph
    """
    response = requests.get(readme_url)
    
    data = response.json()
    file_content = data['content']
    file_content_encoding = data.get('encoding')
    if file_content_encoding == 'base64':
        file_content = base64.b64decode(file_content).decode()
    else :
        logger.warn("Readme not decoded")
        raise Exception("Unexpected encoding type")
    paragraphs = file_content.split("#")
    return paragraphs

def get_month_number(month_str) :
    """
    Transform month_str to month number (ex January -> 1)
    Return int
    """
    try :
        month_number = datetime.datetime.strptime(month_str, "%b").month
    except :
        try : 
            month_number = datetime.datetime.strptime(month_str, "%B").month
        except :
            logger.warn(f"Month {month_str} not decoded")
            raise Exception("Unexpected month format")
    return month_number

def _get_date_week_paragraph(paragraph) :
    """
    Analyze paragraph to find the date associated to a week
    Return datetime object
    """
    date = paragraph.split('\n')[0].split("(")[-1].strip(")").lower()
    month = date
    day = date
    month = month.strip(" 0123456789")
    month_number = get_month_number(month)

    for letter in month :
        day = day.strip(letter)
    day = int(day)
    dt= datetime.datetime.now().date()
    dt = dt.replace(day = day, month = month_number)

    return dt

def get_week_information(paragraphs, nb_weeks=20) :
    """
    Analyze paragraphs to find week text and date
    Rerturn [ ... {"text" str, "date" : datetime, "week" : int} ...]
    """
    data_weeks = []
    for paragraph in paragraphs :
        for week in range(1,nb_weeks+1) :
            if f'week {week}' in paragraph.lower()[:15]:
                data ={}
                data["text"] = paragraph
                data["date"] = _get_date_week_paragraph(paragraph)
                data["week_number"] = week
                data_weeks.append(data)
    logger.info(f"Dates of the weeks {[(data['week_number'],data['date']) for data in data_weeks]}")
    return data_weeks

def get_task_deadline(paragraphs) :
    task_deadlines = {}
    current_year = datetime.datetime.now().year
    for paragraph in paragraphs :
        if "deadlines" in paragraph.lower() :
            lines = paragraph.lower().split("\n")
            for line in lines :
                if 'deadline to complete task' in line :
                    first_part = line.split(":")[0]
                    task_number = int(re.findall(r'\d+', first_part)[0])
                    second_part = line.split(":")[1]
                    results = re.findall(r"((january|february|march|april|may|june|july|august|september|october|november|december)\s[\d]{1,2})", second_part)[0]
                    for result in results :
                        if True in [char.isdigit() for char in result] :
                            month = re.findall(r"(january|february|march|april|may|june|july|august|september|october|november|december)", result)[0]
                            day = re.findall(r'\d+', result)[0]
                    hour_results = re.findall(r'\d+h', second_part)
                    hour = int(re.findall(r'\d+', hour_results[0])[0])
                    dt = datetime.datetime(year = current_year, month = get_month_number(month),day = int(day), hour = int(hour) )
                    is_optional = "optional" in line
                    task_deadlines[task_number] = {"dt" : dt, "optional" : is_optional}
    logger.info(f'Tasks deadline {task_deadlines}')
    return task_deadlines

###############################
### Statistic issue analyze ###
###############################
def get_student_task_info():
    response = requests.get(search_url)
    search_results = response.json()["items"]
    expected_text_in_body = "Statistic Information for Each Category"
    expected_year = datetime.datetime.now().year
    issue= None
    for search_result in search_results :
        if str(expected_year) in search_result["title"] and expected_text_in_body in search_result["body"] :
            issue = search_result
    if issue is None :
        logger.info("No student have completed a task")
        return {}
    body = issue["body"].lower()
    body_per_line = body.split("\n")
    tasks_per_students = {}
    for line in body_per_line :
        if "students with" in line :
            info = line.split(":")
            #expected format for info[0] : {nb_students} students with {nb task} registered tasks:
            numbers = re.findall(r'\d+', info[0])
            nb_task = int(numbers[-1])
            students = info[1].replace(" ", "").strip("*").split(",") 
            tasks_per_students[nb_task] = students
            logger.info(f"{len(students)} students with {nb_task} tasks registered")
    return tasks_per_students

########################
### Calendar analyze ###
########################
def get_course_calendar() :
    request = requests.get(calendar_url)
    gcal = icalendar.Calendar.from_ical(request.text)
    list_events = []
    stockholm_timezone = pytz.timezone('Europe/Stockholm')
    for component in gcal.walk():
        if component.name == "VEVENT":
            event = {}
            event["summary"] =  component.get('summary').to_ical().decode()
            event["dtstart"] = component.get('dtstart').dt.astimezone(stockholm_timezone)
            event["dtend"] = component.get('dtend').dt.astimezone(stockholm_timezone)
            event["location"] = component.get("location").to_ical().decode()
            list_events.append(event)
            
    list_events  = sorted(list_events, key=lambda d: d['dtstart'])
    return list_events


##########################
### Gathering all data ###
##########################
def get_next_week_info(data_weeks,list_events) :
    current_date = datetime.datetime.now().date()
    next_week_paragraph = None
    for data_week in data_weeks :
        delta = (data_week["date"] - current_date).days 
        if  delta > 0 and delta < 8 :
            next_week_paragraph = data_week["text"]
            break
    if next_week_paragraph is None :
        return None
    next_week_events = []
    for event in list_events :
        delta = (event["dtstart"].date() - current_date).days
        if delta < 7 and delta > 0 :
            next_week_events.append(event)
    return next_week_paragraph, next_week_events


##########################
### Writting the mails ###
##########################
def _get_event_text(event) :
    cat = event["summary"]
    if "Laboration" in event["summary"] :
        cat = "Laboratory"
    if "Lektion" in event["summary"] :
        cat = "Lecture"
    date = event['dtstart'].strftime('%A %dth %B')
    ending_hour = event['dtend'].strftime('%Hh%M')
    starting_hour = event['dtstart'].strftime('%Hh%M')
    location = event['location'].replace("\\", "")
    text = f"- {cat} on {date} from {starting_hour} to {ending_hour} in room {location}"
    return text

def _get_week_program_text(program) :
    new_text = ""
    lines = program.replace("*", "-").split("\n")
    for line in lines :
        if len(line) == 0 :
            continue
        if "Week" in line :
            new_line = line.strip().replace("[","").replace("]"," ")
        elif "material" in line :
            new_line = line.replace("[", "\n     -").replace("]",': ').replace(")",'').replace("(","").replace("and","").replace(",","")
        else:
            new_line = line
        new_text += f"{new_line}\n"
    return new_text

def get_common_mail_text(next_week_info) :
    schedule_txt = ""
    for event in next_week_info[1] :
        schedule_txt += _get_event_text(event)+"\n"
    program = _get_week_program_text(next_week_info[0])
    mail = f"Hello,\nHere is the summary for next week DevOps course\n\nProgram of {program}\nSchedule:\n{schedule_txt}"

    return mail

def _send_email(receiver, mail) :
    port = 465   # For starttls
    smtp_server = "smtp.gmail.com"
    sender_email = "devopscourse.kth@gmail.com"
    receiver_email = f"{receiver}@kth.se"
    password = "J5afqZhF3T46"
    context = ssl.create_default_context()
    subject = "[DD2482] DevOps course weekly summary"
    mail =f"{mail}\n\nThis message is automatically generated, please do not respond"
    with smtplib.SMTP_SSL(smtp_server, port, context=context) as server:
        server.login(sender_email, password)
        message = f"From: {sender_email}\nTo: {receiver_email}\nSubject: {subject}\n\n{mail}"
        message = message.encode('utf-8')
        server.sendmail(sender_email,receiver_email,message)

def send_individual_mail(tasks_per_students, task_deadlines, general_mail) :
    for task_number, list_students in tasks_per_students.items() :
        text_task_deadline = "\nTask summary\n"
        if task_number >= len(task_deadlines) :
            text_task_deadline +="You have registered all your tasks! Congrats."
            continue
        next_deadline = task_deadlines[task_number+1]
        text_optional = " "
        if next_deadline["optional"] :
            text_optional = " (optional) "
        date = next_deadline['dt'].strftime('%A %dth %B %H:%M')
        plural ="s"
        if task_number < 2 :
            plural =""
        text_task_deadline += f"You have {task_number} task{plural} registered and your next{text_optional}task is {date}"
        for student in list_students :
            _send_email(student, f"{general_mail}\n{text_task_deadline}")
   
def main() :
    paragraphs = get_readme_info()
    task_deadlines = get_task_deadline(paragraphs)
    data_weeks = get_week_information(paragraphs)
    list_events =get_course_calendar()
    next_week_info = get_next_week_info(data_weeks,list_events)
    common_mail = get_common_mail_text(next_week_info)
    tasks_per_students = get_student_task_info()
    send_individual_mail(tasks_per_students, task_deadlines,common_mail)

if __name__ == "__main__":
    main()