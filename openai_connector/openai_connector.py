import os
import openai
from dotenv import load_dotenv


def call_openai_assistant(tasks, project_logger):
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    openai_client = openai.OpenAI(api_key=openai_api_key)

    project_logger.info("Calling ChatGPT. This can take a while...")

    completion = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=build_message(tasks),
    )

    answer = completion.output_text

    return answer


def build_message(tasks):
    task_lines = "".join(f"\n - {task['name']}" for task in tasks)
    return (
        "Using few words, please help me to prioritize the following tasks. "
        "Answer in portuguese. Explain the importance of each task and why it is "
        "priority or not compared to the others. Also estimate the time to complete each one."
        "\nInstructions:"
        "\n- Be brief and explain the prioritization."
        "\n- Tasks are in portuguese."
        "\n- IMPORTANT: Answer with a pure JSON format without saying it is JSON."
        "\n{\n\t'task_name': {\n\t\t'priority_number': <int>,"
        "\n\t\t'priority_level': <high|medium|low>, \n\t\t'comment': <str>\n\t}\n}"
        "\n- Conclude with a general one line comment about the tasks."
        "\n- Remove ':' character from task names so the output JSON remains valid."
        "\n- Different projects mean no related tasks."
        "\n- Make task names shorter."
        "\nTasks:"
        f"{task_lines}"
    )
