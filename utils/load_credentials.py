import os


def _get_required_env(env_key, project_logger):
    env_value = os.getenv(env_key)
    if env_value:
        return env_value

    error_message = f"Missing required environment variable: {env_key}"
    project_logger.error(error_message)
    raise ValueError(error_message)


def load_notion_credentials(project_logger):
    project_logger.debug("Getting Notion credentials from .env...")

    notion_keys = {
        "database_id": _get_required_env("NOTION_DATABASE_ID", project_logger),
        "api_key": _get_required_env("NOTION_API_KEY", project_logger),
    }

    project_logger.debug("Finished getting Notion credentials.")

    return notion_keys


def load_email_config(project_logger):
    project_logger.debug("Getting EMAIL credentials from .env...")

    email_config = {
        "email_from": _get_required_env("EMAIL_FROM", project_logger),
        "email_to": _get_required_env("EMAIL_TO", project_logger),
        "display_name": _get_required_env("DISPLAY_NAME", project_logger),
    }

    project_logger.debug("Finished getting EMAIL credentials.")

    return email_config
