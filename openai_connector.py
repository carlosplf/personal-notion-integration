import os
import openai
from dotenv import load_dotenv


def call_openai_assistant(tasks):
    load_dotenv()
    openai.api_key = os.getenv("OPENAI_KEY")

    print("Calling ChatGPT. This can take a while...")

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "assistant",
                "content": build_message(tasks)
            }
        ]
    )

    answer = completion.choices[0].message.content
    return answer


def build_message(tasks):
    message = "Using few words, please help me to prioritize " + \
        "the following tasks. Answer in portuguese. Explain the " + \
        "importance of each one of the tasks and why they are " + \
        "piority or not when compared to the others. " + \
        "Also estimate the time to complete each one." + \
        "\nInstructions:" + \
        "\n- Be brief and explain the prioritization." + \
        "\n- Tasks are in portuguese." + \
        "\n- Answer with a JSON format: " + \
        "\n{\n\t'task_name': {\n\t\t'priority_number': <int>," + \
        "\n\t\t'priority_level': <high|medium|low>, \n\t\t'comment': " + \
        "<str>\n\t}\n}" + \
        "\n- Conclude with a general one line comment about the tasks." + \
        "\n- Remove ':' character from tasks names so the output JSON " + \
        "is always valid." + \
        "\n- Make task names shorter." + \
        "\nTasks: "

    for task in tasks:
        message += "\n - " + task["name"]

    return message
