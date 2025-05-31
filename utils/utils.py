"""
This module contains miscellaneous utility functions for the bot.
"""

def clean_name(name):
    """
    Cleans a player's name by replacing backtick characters (`)
    with single quotes (') to prevent formatting issues in Discord messages.

    Args:
        name (str): The player name string to clean.

    Returns:
        str: The cleaned player name string.
    """
    return name.replace("`", "´")
