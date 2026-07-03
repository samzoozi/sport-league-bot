from telegram import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
)
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.config import BOT_TOKEN
from bot.handlers import admin, player, setup, signup, skips

PLAYER_COMMANDS = [
    BotCommand("register", "Register with your e-transfer email"),
    BotCommand("setemail", "Update just your e-transfer email"),
    BotCommand("emails", "List everyone's e-transfer email"),
    BotCommand("balance", "Show your balance and recent transactions"),
    BotCommand("squad", "Re-post the current month's signup card"),
    BotCommand("skip", "Skip the next game and offer your spot to the waitlist"),
    BotCommand("waitlist", "Show who's on the waitlist for the next game"),
    BotCommand("addtowaitlist", "Join the waitlist for the next game"),
    BotCommand("leavewaitlist", "Leave the waitlist for the next game"),
    BotCommand("nextgame", "Who's playing in the next game"),
    BotCommand("games", "This month's game schedule"),
    BotCommand("help", "Show available commands"),
]

ADMIN_COMMANDS = PLAYER_COMMANDS + [
    BotCommand("setupgroup", "One-time setup — tap a weekday"),
    BotCommand("newmonth", "Open signups: /newmonth <YYYY-MM> <total_cost>"),
    BotCommand(
        "deletemonth", "Delete an open (non-finalized) month: /deletemonth <YYYY-MM>"
    ),
    BotCommand("addplayer", "Add a player to the squad"),
    BotCommand("removeplayer", "Remove a player from the squad"),
    BotCommand("finalize", "Lock the squad and charge everyone their share"),
    BotCommand("charge", "Charge a player: /charge @user <amount> <desc>"),
    BotCommand("credit", "Credit a player: /credit @user <amount> <desc>"),
    BotCommand(
        "chargeall",
        "Charge a whole month's squad: /chargeall <YYYY-MM> <amount> <desc>",
    ),
    BotCommand(
        "creditall",
        "Credit a whole month's squad: /creditall <YYYY-MM> <amount> <desc>",
    ),
    BotCommand("paid", "Record a payment: /paid @user <amount>"),
    BotCommand("balances", "Show everyone's balance"),
]


async def set_bot_commands(bot) -> None:
    """Push the two Telegram '/' command menus. Only invoked automatically by
    run_polling()/run_webhook() via post_init — NOT by plain
    Application.initialize() (what the Lambda handler uses), so
    scripts/set_webhook.py calls this explicitly once after deploying."""
    await bot.set_my_commands(PLAYER_COMMANDS, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(
        ADMIN_COMMANDS, scope=BotCommandScopeAllChatAdministrators()
    )


async def _post_init(application: Application) -> None:
    await set_bot_commands(application.bot)


def build_application() -> Application:
    application = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    application.add_handler(CommandHandler("register", player.register))
    application.add_handler(CommandHandler("setemail", player.setemail))
    application.add_handler(CommandHandler("help", player.help_))
    application.add_handler(CommandHandler("emails", player.emails))
    application.add_handler(CommandHandler("balance", player.balance))
    application.add_handler(CommandHandler("squad", player.squad))
    application.add_handler(CommandHandler("waitlist", player.waitlist))
    application.add_handler(CommandHandler("addtowaitlist", player.addtowaitlist))
    application.add_handler(CommandHandler("leavewaitlist", player.leavewaitlist))
    application.add_handler(CommandHandler("skip", skips.skip_cmd))
    application.add_handler(CommandHandler("nextgame", player.nextgame))
    application.add_handler(CommandHandler("games", player.games))
    application.add_handler(CommandHandler("setupgroup", setup.setupgroup))
    application.add_handler(CommandHandler("newmonth", admin.newmonth))
    application.add_handler(CommandHandler("deletemonth", admin.deletemonth))
    application.add_handler(CommandHandler("addplayer", admin.addplayer))
    application.add_handler(CommandHandler("removeplayer", admin.removeplayer))
    application.add_handler(CommandHandler("finalize", admin.finalize))
    application.add_handler(CommandHandler("charge", admin.charge))
    application.add_handler(CommandHandler("credit", admin.credit))
    application.add_handler(CommandHandler("chargeall", admin.chargeall))
    application.add_handler(CommandHandler("creditall", admin.creditall))
    application.add_handler(CommandHandler("paid", admin.paid))
    application.add_handler(CommandHandler("balances", admin.balances))
    application.add_handler(
        CallbackQueryHandler(signup.signup_callback, pattern=r"^signup:")
    )
    application.add_handler(
        CallbackQueryHandler(skips.skip_pick_callback, pattern=r"^skip:")
    )
    application.add_handler(
        CallbackQueryHandler(skips.replace_callback, pattern=r"^replace:")
    )
    application.add_handler(
        CallbackQueryHandler(setup.setupgroup_callback, pattern=r"^setupgroup:")
    )

    return application
