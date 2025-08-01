from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
import datetime
import asyncio


TOKEN = "8183525050:AAGVpW5Iowe5zLFZJZ7cvwQWmE_wcBCXdO8"  # Token for bot
API = "https://api.telegram.org/bot8183525050:AAGVpW5Iowe5zLFZJZ7cvwQWmE_wcBCXdO8/getUpdates" # Link where you can see all messages

scheduler = BackgroundScheduler()
user_jobs = {}  # { chat_id: [(job_id, time, message)] }

# Global variable to store the event loop
bot_event_loop = None


# --- Send reminder function ---
def send_reminder(application, loop, chat_id, text):
    print(f"⏰ Sending reminder to {chat_id}: {text}")
    asyncio.run_coroutine_threadsafe(
        application.bot.send_message(chat_id=chat_id, text=f"⏰ Reminder: {text}"),
        loop
    )


# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Use:\n"
        "/add_notification YYYY-MM-DD HH:MM Your message\n"
        "/list to view/delete reminders"
    )


# --- /add_notification ---
async def add_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        args = context.args

        if len(args) < 3:
            await update.message.reply_text("Format:\n/add_notification YYYY-MM-DD HH:MM Your message")
            return

        date_str, time_str = args[0], args[1]
        message_text = " ".join(args[2:])

        run_time = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        if run_time < datetime.datetime.now():
            await update.message.reply_text("⛔ Time is in the past!")
            return

        job_id = f"{chat_id}-{run_time.timestamp()}"

        scheduler.add_job(
            send_reminder,
            'date',
            run_date=run_time,
            args=[context.application, bot_event_loop, chat_id, message_text],
            id=job_id
        )

        user_jobs.setdefault(chat_id, []).append((job_id, run_time, message_text))

        await update.message.reply_text(
            f"✅ Reminder set for {run_time.strftime('%Y-%m-%d %H:%M')}:\n{message_text}"
        )

    except Exception as e:
        await update.message.reply_text("❌ Failed to set reminder. Check your format.")
        print("Error adding reminder:", e)



# --- /list ---
async def list_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = user_jobs.get(chat_id, [])

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    message = f"🕒 Current time: {now}\n\n"

    if not jobs:
        message += "📭 No upcoming reminders."
        await update.message.reply_text(message)
        return

    message += "📋 Your reminders:\n"
    buttons = []

    # Separate one-time and weekly jobs
    one_time_jobs = [job for job in jobs if isinstance(job[1], datetime.datetime)]
    weekly_jobs = [job for job in jobs if isinstance(job[1], str)]

    # Sort one-time jobs by datetime
    one_time_jobs = sorted(one_time_jobs, key=lambda x: x[1])

    message += "📅 One-time reminders:\n"
    buttons = []
    idx = 0
    for job_id, time, text in one_time_jobs:
        idx += 1
        message += f"{idx}. {time.strftime('%Y-%m-%d %H:%M')} - {text}\n"
        buttons.append([InlineKeyboardButton(f"❌ Delete #{idx}", callback_data=f"delete:{job_id}")])

    if weekly_jobs:
        message += "\n🔁 Weekly reminders:\n"
        for job_id, time_str, text in weekly_jobs:
            idx += 1
            message += f"{idx}. {time_str} - {text}\n"
            buttons.append([InlineKeyboardButton(f"❌ Delete #{idx}", callback_data=f"delete:{job_id}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(message, reply_markup=reply_markup)


# --- Button handler ---
async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("delete:"):
        job_id = data.split("delete:")[1]
        chat_id = query.message.chat.id

        try:
            scheduler.remove_job(job_id)
            user_jobs[chat_id] = [job for job in user_jobs[chat_id] if job[0] != job_id]
            await query.edit_message_text("🗑️ Reminder deleted.")
        except JobLookupError:
            await query.edit_message_text("⚠️ Reminder already deleted or not found.")


async def weekly_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        args = context.args

        print("Command args:", args)  # TEMP: see how it's parsed

        if len(args) < 3:
            await update.message.reply_text(
                "❌ Failed to set weekly reminder.\n\n"
                "✅ Format:\n"
                "`/weekly_notification <day(1-7)> <HH:MM> Your message`\n\n"
                "💬 Example:\n"
                "`/weekly_notification 3 16:45 Drink water`",
                parse_mode="Markdown"
            )
            return

        # Extract and validate input
        weekday = int(args[0])
        if weekday < 1 or weekday > 7:
            await update.message.reply_text("❌ Day must be between 1 (Monday) and 7 (Sunday).")
            return

        time_str = args[1]
        time_str = time_str.replace("：", ":")
        hour, minute = map(int, time_str.split(":"))
        message_text = " ".join(args[2:])

        # APScheduler uses 0–6 (Mon–Sun), user provides 1–7
        cron_weekday = (weekday - 1) % 7
        job_id = f"{chat_id}-weekly-{cron_weekday}-{hour}-{minute}-{hash(message_text)}"

        # Schedule the job
        scheduler.add_job(
            send_reminder,
            'cron',
            day_of_week=cron_weekday,
            hour=hour,
            minute=minute,
            args=[context.application, bot_event_loop, chat_id, message_text],
            id=job_id
        )

        # Store job info
        user_jobs.setdefault(chat_id, []).append((job_id, f"Weekly on {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][cron_weekday]} {time_str}", message_text))

        await update.message.reply_text(
            f"✅ Weekly reminder set for day {weekday} at {time_str}:\n{message_text}"
        )

    except Exception as e:
        await update.message.reply_text("❌ Failed to set weekly reminder. Format: /weekly_notification <day(1-7)> <HH:MM> Your message")
        print("Error adding weekly reminder:", e)


# --- Main ---
def main():
    global bot_event_loop

    app = ApplicationBuilder().token(TOKEN).build()
    bot_event_loop = asyncio.get_event_loop_policy().get_event_loop() # Store the bot's event loop

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_notification", add_notification))
    app.add_handler(CommandHandler("list", list_notifications))
    app.add_handler(CommandHandler("weekly_notification", weekly_notification))
    app.add_handler(CallbackQueryHandler(handle_delete_callback))

    scheduler.start()
    app.run_polling()


if __name__ == "__main__":
    main()
