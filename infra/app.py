#!/usr/bin/env python3
from pathlib import Path

from aws_cdk import App
from dotenv import load_dotenv

from stacks.bot_stack import BotStack

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = App()
BotStack(app, "HangarSportBotStack")
app.synth()
