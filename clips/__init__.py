"""Host-side clip pipeline: turns the game server's HLTV demos into short vertical videos.

Runs on the Discord machine itself, not inside the bot's container: it needs Steam with CS 1.6, an X server on
the GPU and a PulseAudio sink (see clips/README.md). Its only output is a folder of finished clips that the bot's
``cogs/clips.py`` reads.
"""
