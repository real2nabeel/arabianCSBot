# Arabian Servers Discord Bot

This bot is designed for the Arabian Servers Discord community. It provides various features to enhance the server members' experience, including moderation tools, utility commands, and fun interactions.

## Features

- **Moderation:** Commands for managing users, such as kicking, banning, and muting.
- **Utility:** Helpful commands like user information, server statistics, and polls.
- **Fun:** Interactive commands like memes, games, and quotes.
- **Customizable:** The bot can be configured to suit the specific needs of the server.

## Commands

The bot's commands are organized into cogs. Here's a list of available commands:

### Moderation Cog
- `!kick <user> [reason]`: Kicks a user from the server.
- `!ban <user> [reason]`: Bans a user from the server.
- `!mute <user> [duration] [reason]`: Mutes a user for a specified duration.
- `!unmute <user>`: Unmutes a user.

### Utility Cog
- `!userinfo <user>`: Displays information about a user.
- `!serverinfo`: Shows details about the server.
- `!poll <question> <option1> <option2> ...`: Creates a poll with multiple options.

### Fun Cog
- `!meme`: Fetches a random meme.
- `!quote`: Displays a random quote.
- `!rps <choice>`: Plays a game of Rock, Paper, Scissors with the bot.

*(Please note: This is a sample list of commands. The actual commands may vary depending on the bot's current configuration.)*

## Setup and Running the Bot

To set up and run the bot, follow these steps:

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/arabian-servers-bot.git
   cd arabian-servers-bot
   ```

2. **Install dependencies:**
   Make sure you have Python 3.8 or higher installed. Then, install the required packages using pip:
   ```bash
   pip install -r requirements.txt
   ```

3. **Create a Discord Bot Token:**
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications).
   - Create a new application.
   - Navigate to the "Bot" tab and click "Add Bot."
   - Copy the bot token. **Keep this token secret!**

4. **Configure the Bot:**
   - Rename the `.env.example` file to `.env`.
   - Open the `.env` file and add your Discord bot token:
     ```
     DISCORD_TOKEN=your_bot_token_here
     ```
   - You may also need to configure other settings in this file, such as database credentials or API keys, depending on the bot's features.

5. **Run the Bot:**
   ```bash
   python main.py
   ```

   The bot should now be online and connected to your Discord server.

## Contributing

Contributions are welcome! If you have any ideas, suggestions, or bug fixes, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.