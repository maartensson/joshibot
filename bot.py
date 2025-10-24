# bot.py
import os
import json
import logging
import asyncio
import time
import csv
from datetime import datetime, timedelta, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from config import settings


LAST_UPDATE_TIME = 0

# Optionen
MODES = ["Van", "Car", "Tent", "Hammock", "In someone elses", "Other"]
WEEK_CHOICES = [("Full week", 1.0), ("Half week", 0.5)]

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)


# -----------------------------
# File Helpers
# -----------------------------
def _ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f)


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -----------------------------
# Wochen-Funktionen (Nov -> Apr)
# -----------------------------
def get_week_dates_nov_apr():
    """
    Liefert Liste von Montage (date-Objekte) von Anfang November bis Ende April.
    """
    today = date.today()
    year = today.year
    start = date(year, 11, 1)
    end = date(year + 1, 4, 30)

    # ersten Montag >= start finden
    start_monday = start
    while start_monday.weekday() != 0:
        start_monday += timedelta(days=1)

    weeks = []
    cur = start_monday
    while cur <= end:
        weeks.append(cur)
        cur += timedelta(days=7)
    return weeks


def fmt_week_label_iso(dt: date):
    """Format for Weekly Summary: '03.11.-09.11.' (always two digits)."""
    start = dt
    end = start + timedelta(days=6)
    return f"{start.day:02}.{start.month:02}.-{end.day:02}.{end.month:02}."


def month_week_label(dt: date):
    """
    Monat + Index innerhalb des Monats basierend auf Montage.
    Beispiel: für den ersten Montag im November => 'Nov1'
    """
    # Erzeuge alle Montage im Monat
    first_day = dt.replace(day=1)
    # Bestimme letzter Tag des Monats
    if first_day.month == 12:
        last_day = date(first_day.year, 12, 31)
    else:
        next_month_first = first_day.replace(month=first_day.month + 1, day=1)
        last_day = next_month_first - timedelta(days=1)

    # Erzeuge Liste aller Montage im Monat (>=1. Montag)
    mondays = []
    cur = first_day
    # Vorwärts bis erster Montag
    while cur.weekday() != 0 and cur <= last_day:
        cur += timedelta(days=1)
    while cur <= last_day:
        mondays.append(cur)
        cur += timedelta(days=7)

    # Index im Monat (1-based)
    try:
        idx = mondays.index(dt) + 1
    except ValueError:
        # Falls dt nicht in der Liste ist (sollte nicht passieren), fallback:
        idx = sum(1 for m in mondays if m <= dt)
        if idx == 0:
            idx = 1
    return f"{dt.strftime('%b')}{idx}"  # z.B. "Nov1"


# -----------------------------
# Anzeige-Hilfen (Balken & Farben)
# -----------------------------
def symbol_color_for_cumulative(cumulative):
    if cumulative <= 30:
        return "green"
    if cumulative <= 50:
        return "orange"
    return "red"


def block_for_ten(color):
    if color == "green":
        return "🟩"
    if color == "orange":
        return "🟧"
    return "🟥"


def circle_for_rest(color):
    if color == "green":
        return "🟢"
    if color == "orange":
        return "🟠"
    return "🔴"


def build_visual_bar(count):
    """
    Visualisierung:
    - 1 Viereck (🟩/🟧/🟥) = 10 Personen
    - 1 Kreis (🟢/🟠/🔴) = 5 Personen (nicht Rest!)
    - Farbe abhängig von kumulativer Summe
    """
    symbols = []
    
    # Ganze 10er-Blöcke
    tens = count // 10
    remainder = count % 10
    
    # Zähle 10er-Blöcke
    values = [10] * tens
    
    # Wenn mind. 15 Personen erreicht sind (also remainder >= 5), füge einen "5er-Kreis" hinzu
    if remainder >= 5:
        values.append(5)

    cumulative = 0
    for v in values:
        cumulative += v
        color = symbol_color_for_cumulative(cumulative)
        if v == 10:
            symbols.append(block_for_ten(color))
        elif v == 5:
            symbols.append(circle_for_rest(color))

    return "".join(symbols)


# -----------------------------
# Meal Poll
# -----------------------------
def get_days_with_dates_meal():
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    days = []
    for i in range(7):
        d = monday + timedelta(days=i + 7)
        days.append((d.strftime("%A"), d.strftime("%d.%m.%Y")))
    return days


def get_color_icon(count):
    if count <= 25:
        return "🟩"
    if count <= 50:
        return "🟧"
    return "🟥"


def format_meal_text(polls):
    text = "🍽 *Weekly Meal Participation*\n\n"
    for day, users in polls.items():
        count = len(users)
        icon = get_color_icon(count)
        user_list = "\n".join([f"- {u}" for u in users]) if users else "–"
        text += f"{icon} *{day}* — {count}\n{user_list}\n\n"
    return text


def build_meal_keyboard(polls=None, current_user=None):
    days_with_dates = get_days_with_dates_meal()
    buttons = []
    for day_name, date_str in days_with_dates:
        label = f"{day_name} ({date_str})"
        if polls and current_user and current_user in polls.get(day_name, []):
            label = f"✅ {label}"
        else:
            label = f"⬜ {label}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"MEAL|{day_name}")])
    return InlineKeyboardMarkup(buttons)


async def handle_meal_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_UPDATE_TIME
    query = update.callback_query
    user = query.from_user.first_name
    day = query.data.split("|", 1)[1]

    data = load_json(settings.meal_file)
    polls = data.get("polls", {})

    if day not in polls:
        polls[day] = []

    if user in polls[day]:
        polls[day].remove(user)
    else:
        polls[day].append(user)

    data["polls"] = polls
    save_json(settings.meal_file, data)
    await query.answer("✅ Updated!")

    text = format_meal_text(polls)
    now = time.time()

    if now - LAST_UPDATE_TIME > settings.update_interval:
        LAST_UPDATE_TIME = now
        msg_id = load_json(settings.meal_message_file).get("message_id")
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=settings.chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=build_meal_keyboard(polls),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.warning(f"Meal global edit failed: {e}")

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=build_meal_keyboard(polls, current_user=user),
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def post_weekly_meal(app):
    days_with_dates = get_days_with_dates_meal()
    polls = {day: [] for day, _ in days_with_dates}

    save_json(settings.meal_file, {"polls": polls})

    text = format_meal_text(polls)

    msg = await app.bot.send_message(
        chat_id=settings.chat_id,
        message_thread_id=settings.thread_id_meal,
        text=text,
        reply_markup=build_meal_keyboard({"polls": polls}),
        parse_mode="Markdown"
    )

    logging.info(f"📅 Meal poll posted: {msg.message_id}")
    save_json(settings.meal_message_file, {"message_id": msg.message_id})
    logging.info(f"Meal poll posted (id {msg.message_id})")


# -----------------------------
# Bounceland Poll
# -----------------------------
def init_bounceland_structure():
    weeks = get_week_dates_nov_apr()
    data = {
        "users": {},  # uid -> {"name":..., "username":..., "modes": [...], "weeks": {wk_iso:choice}}
        "weeks": {w.isoformat(): {"Full week": [], "Half week": [], "Not really": []} for w in weeks},
    }
    return data


def format_bounceland_text(data):
    """
    Weekly Summary: Date + visual bar + integer score
    """
    text = "*Bounceland Weekly Summary*\n\n"
    for wk_iso in sorted(data.get("weeks", {}).keys()):
        groups = data["weeks"][wk_iso]
        full = len(groups.get("Full week", []))
        half = len(groups.get("Half week", []))
        score = full * 1.0 + half * 0.5
        bar = build_visual_bar(int(round(score))) if score >= 1 else build_visual_bar(int(round(score)))
        label = fmt_week_label_iso(datetime.fromisoformat(wk_iso).date())
        text += f"{label} {bar} {int(score)}\n"
    return text


def build_bounceland_keyboard(data=None, current_user=None):
    """
    Keyboard:
    - Jede Mode in eigener Zeile.
    - Für jede Woche: eine Zeile mit [emoji MonthWeek] [Full] [Half] [Not]
      - Emoji = indicator basierend auf total score
      - MonthWeek = e.g. Nov1, Nov2, Dec1 ...
    """
    kb = []

    # Modes — jeweils eigene Zeile
    for mode in MODES:
        label = mode
        if data and current_user:
            user_info = data.get("users", {}).get(current_user, {})
            if mode in user_info.get("modes", []):
                label = f"✅ {mode}"
        kb.append([InlineKeyboardButton(label, callback_data=f"MODE|{mode}")])

    # Weeks: show as MonthIndex (Nov1, Dec1, ...) with emoji indicator
    weeks = list(data.get("weeks", {}).keys()) if data else [w.isoformat() for w in get_week_dates_nov_apr()]
    for wk_iso in weeks:
        wk_date = datetime.fromisoformat(wk_iso).date()
        groups = data.get("weeks", {}).get(wk_iso, {"Full week": [], "Half week": [], "Not really": []}) if data else {"Full week": [], "Half week": [], "Not really": []}
        full = len(groups.get("Full week", []))
        half = len(groups.get("Half week", []))
        score = full * 1.0 + half * 0.5

        if score <= 30:
            emoji = "🟢"
        elif score <= 50:
            emoji = "🟠"
        else:
            emoji = "🔴"

        label_week = month_week_label(wk_date)  # e.g. "Nov1"
        row = []
        for choice_key, _ in WEEK_CHOICES:
            short = choice_key.split()[0]  # Full / Half / Not
            btn_label = short
            if data and current_user:
                user_weeks = data.get("users", {}).get(current_user, {}).get("weeks", {})
                if user_weeks.get(wk_iso) == choice_key:
                    btn_label = f"✅ {short}"
            row.append(InlineKeyboardButton(btn_label, callback_data=f"WEEK|{wk_iso}|{choice_key}"))
        # leftmost button shows emoji + monthWeek; INFO callback so it doesn't interfere
        kb.append([InlineKeyboardButton(f"{emoji} {label_week}", callback_data=f"INFO|{wk_iso}")] + row)

    return InlineKeyboardMarkup(kb)


# -----------------------------
# Handlers for Bounceland & Meal
# -----------------------------
async def handle_bounceland_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # use unique id as key if possible
    uid = str(query.from_user.id)
    name = query.from_user.first_name or ""
    username = f"@{query.from_user.username}" if query.from_user.username else ""
    mode = query.data.split("|", 1)[1]

    data = load_json(settings.bounce_file)
    if not data:
        data = init_bounceland_structure()

    users = data.setdefault("users", {})
    user_info = users.setdefault(uid, {"name": name, "username": username, "modes": [], "weeks": {}})

    if mode in user_info["modes"]:
        user_info["modes"].remove(mode)
        await query.answer(f"❌ {mode} removed")
    else:
        user_info["modes"].append(mode)
        await query.answer(f"✅ {mode} added")

    save_json(settings.bounce_file, data)

    # Update global message if exists
    msg_id = load_json(settings.bounce_message_file).get("message_id")
    text = format_bounceland_text(data)
    try:
        if msg_id:
            await context.bot.edit_message_text(
                chat_id=settings.chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=build_bounceland_keyboard(data, current_user=uid),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.warning(f"Bounceland edit failed: {e}")


async def handle_bounceland_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = str(query.from_user.id)
    name = query.from_user.first_name or ""
    username = f"@{query.from_user.username}" if query.from_user.username else ""
    _, wk_iso, choice_key = query.data.split("|", 2)

    data = load_json(settings.bounce_file)
    if not data:
        data = init_bounceland_structure()

    users = data.setdefault("users", {})
    if uid not in users:
        users[uid] = {"name": name, "username": username, "modes": [], "weeks": {}}

    prev_choice = users[uid]["weeks"].get(wk_iso)
    if prev_choice and uid in data["weeks"].get(wk_iso, {}).get(prev_choice, []):
        data["weeks"][wk_iso][prev_choice].remove(uid)

    if prev_choice == choice_key:
        users[uid]["weeks"].pop(wk_iso, None)
        await query.answer("✅ Selection removed")
    else:
        data["weeks"].setdefault(wk_iso, {"Full week": [], "Half week": [], "Not really": []})
        if uid not in data["weeks"][wk_iso].get(choice_key, []):
            data["weeks"][wk_iso][choice_key].append(uid)
        users[uid]["weeks"][wk_iso] = choice_key
        await query.answer(f"✅ {choice_key}")

    save_json(settings.bounce_file, data)

    # Update global message if exists
    msg_id = load_json(settings.bounce_message_file).get("message_id")
    text = format_bounceland_text(data)
    try:
        if msg_id:
            await context.bot.edit_message_text(
                chat_id=settings.chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=build_bounceland_keyboard(data, current_user=uid),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.warning(f"Bounceland edit failed: {e}")


async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Choose Full / Half for this week.")


async def post_bounceland_overview(app):
    data = load_json(settings.bounce_file)
    if not data:
        data = init_bounceland_structure()
        save_json(settings.bounce_file, data)
    text = format_bounceland_text(data)
    msg = await app.bot.send_message(
    chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland,
    text=text,
    reply_markup=build_bounceland_keyboard(data),
    parse_mode="Markdown"
)
    save_json(settings.bounce_message_file, {"message_id": msg.message_id})
    logging.info(f"Bounceland Overview posted (id {msg.message_id})")


# -----------------------------
# CSV Export (user_id,username,name,...weeks...)
# -----------------------------
def generate_bounceland_csv(path=settings.bounce_csv):
    data = load_json(settings.bounce_file)
    if not data:
        data = init_bounceland_structure()

    weeks = sorted(data.get("weeks", {}).keys())  # iso strings
    header = ["user_id", "username", "name"] + MODES + [fmt_week_label_iso(datetime.fromisoformat(w).date()) for w in weeks]

    rows = [header]
    users = data.get("users", {})
    for uid, info in users.items():
        row = [uid, info.get("username", ""), info.get("name", "")]
        modes_selected = info.get("modes", [])
        for m in MODES:
            row.append("1" if m in modes_selected else "0")
        for w in weeks:
            status = info.get("weeks", {}).get(w)
            if status is None:
                row.append("0")
            else:
                val = next((s for k, s in WEEK_CHOICES if k == status), 0.0)
                row.append(str(val))
        rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return path


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logging.info(f"/export requested by {user_id}")
    csv_path = generate_bounceland_csv()
    try:
        with open(csv_path, "rb") as f:
            await context.bot.send_document(chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland, document=f, filename=os.path.basename(csv_path))
    except Exception as e:
        logging.error(f"Export failed: {e}")
        await update.message.reply_text("❌ Export failed.")

# -----------------------------
# Reset Command
# -----------------------------
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if settings.owner_id and user_id != settings.owner_id:
        await update.message.reply_text("⛔️ Only the owner can do this.")
        return

    try:
        # 1️⃣ Backup/Export vor Reset
        csv_path = generate_bounceland_csv()
        with open(csv_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=os.path.basename(csv_path),
                caption="📦 Automatic export before reset"
            )

        # 2️⃣ Reset Bounceland data
        data = init_bounceland_structure()
        save_json(settings.bounce_file, data)

        await update.message.reply_text("✅ Bounceland data has been deleted (backup sent).")
        logging.info("⚠️ Bounceland JSON was cleared (after automatic backup).")

    except Exception as e:
        logging.error(f"Reset failed: {e}")
        await update.message.reply_text("❌ Error during reset.")

# -----------------------------
# CSV Import: only add new users (won't overwrite existing)
# -----------------------------

# We'll track import state per admin who initiated import
# stored in bot_data['awaiting_import_from'] = user_id
async def cmd_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if settings.owner_id and user_id != settings.owner_id:
        await update.message.reply_text("⛔️ Only the owner can do this.")
        return
    # set awaiting flag
    context.application.bot_data["awaiting_import_from"] = user_id
    await context.bot.send_message(
    chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland,
    text="Please send the CSV file now (exported CSV). The import will only add new users.")


async def cmd_cancel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.application.bot_data.get("awaiting_import_from") == user_id:
        context.application.bot_data.pop("awaiting_import_from", None)
        await update.message.reply_text("Import cancelled.")
    else:
        await update.message.reply_text("No active import process found.")


async def handle_document_for_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only accept if user initiated import via /import
    from_user = update.effective_user
    awaiting = context.application.bot_data.get("awaiting_import_from")
    if awaiting != from_user.id:
        # ignore unrelated uploads
        await update.message.reply_text("No import requested. If you want to import, send /import first.")
        return

    # proceed to download and parse CSV
    document = update.message.document
    if not document:
        await update.message.reply_text("No file found.")
        return

    # download file
    file = await context.bot.get_file(document.file_id)
    local_path = f"/tmp/{document.file_name}"
    await file.download_to_drive(local_path)

    # parse CSV
    added = 0
    skipped = 0
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        await update.message.reply_text(f"❌ CSV could not be read: {e}")
        context.application.bot_data.pop("awaiting_import_from", None)
        return

    data = load_json(settings.bounce_file)
    if not data:
        data = init_bounceland_structure()

    weeks_iso_list = sorted(data.get("weeks", {}).keys())
    # Build mapping from header week label -> wk_iso by comparing fmt_week_label_iso
    header_to_iso = {}
    # Build mapping of fmt label for each wk_iso
    fmt_map = {fmt_week_label_iso(datetime.fromisoformat(w).date()): w for w in weeks_iso_list}

    for row in rows:
        uid = row.get("user_id") or row.get("user") or row.get("id")
        if not uid:
            # skip lines without id
            skipped += 1
            continue
        uid = str(uid)
        if uid in data.get("users", {}):
            skipped += 1
            continue

        # create user entry
        username = row.get("username", "") or ""
        name = row.get("name", "") or ""
        # modes: read the first matching MODE column if present (older csv had MODE columns)
        modes_selected = []
        for m in MODES:
            val = row.get(m)
            if val and val.strip() in ("1", "1.0", "true", "True"):
                modes_selected.append(m)
        # also if there's a "mode" field single value
        if not modes_selected and row.get("mode"):
            modeval = row.get("mode")
            if modeval in MODES:
                modes_selected.append(modeval)

        # weeks: read header columns that match fmt_map keys
        user_weeks = {}
        for header_col, cell in row.items():
            if header_col in ("user_id", "username", "name") or header_col in MODES or header_col == "mode":
                continue
            if cell is None:
                continue
            col_label = header_col
            # try to map header label to wk_iso
            wk_iso = fmt_map.get(col_label)
            if not wk_iso:
                continue
            val = cell.strip()
            if val == "1" or val == "1.0":
                user_weeks[wk_iso] = "Full week"
            elif val == "0.5":
                user_weeks[wk_iso] = "Half week"
            elif val == "0" or val == "":
                # leave as not present (Not really)
                pass

        # add to data
        data.setdefault("users", {})
        data["users"][uid] = {
            "name": name,
            "username": username,
            "modes": modes_selected,
            "weeks": user_weeks,
        }
        # also insert uid into weeks lists for each chosen week
        for wk_iso, choice in user_weeks.items():
            data["weeks"].setdefault(wk_iso, {"Full week": [], "Half week": [], "Not really": []})
            if uid not in data["weeks"][wk_iso].get(choice, []):
                data["weeks"][wk_iso][choice].append(uid)
        added += 1

    save_json(settings.bounce_file, data)
    context.application.bot_data.pop("awaiting_import_from", None)
    await context.bot.send_message(
    chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland,
    text=f"✅ Import completed. {added} new users added, {skipped} skipped.")


# -----------------------------
# Callback Router
# -----------------------------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qd = update.callback_query.data
    if not qd:
        await update.callback_query.answer()
        return
    if qd.startswith("MEAL|"):
        await handle_meal_button(update, context)
    elif qd.startswith("MODE|"):
        await handle_bounceland_mode(update, context)
    elif qd.startswith("WEEK|"):
        await handle_bounceland_week(update, context)
    elif qd.startswith("INFO|"):
        await handle_info(update, context)
    else:
        await update.callback_query.answer()


# -----------------------------
# Heartbeat
# -----------------------------
async def heartbeat():
    while True:
        logging.info("💓 Bot alive - waiting for commands...")
        await asyncio.sleep(60)


# -----------------------------
# Commands
# -----------------------------
async def cmd_postnow_meal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if settings.owner_id and user_id != settings.owner_id:
        await update.message.reply_text("⛔️ Only the owner can do this.")
        return
    await post_weekly_meal(context.application)
    await context.bot.send_message(
    chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland,
    text="✅ New weekly poll posted.")


async def cmd_bounceland(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if settings.owner_id and user_id != settings.owner_id:
        await update.message.reply_text("⛔️ Only the owner can do this.")
        return
    await post_bounceland_overview(context.application)
    await context.bot.send_message(
    chat_id=settings.chat_id,
    message_thread_id=settings.thread_id_bounceland,
    text="✅ Bounceland Overview posted.")


# -----------------------------
# Main
# -----------------------------
async def main():
    logging.info(settings.model_dump())
    # ensure files
    _ensure_file(settings.meal_file, {"polls": {}})
    _ensure_file(settings.meal_message_file, {})
    _ensure_file(settings.bounce_file, init_bounceland_structure())
    _ensure_file(settings.bounce_message_file, {})

    if not settings.telegram_bot_token:
        logging.error("TELEGRAM_BOT_TOKEN NOT SET, exiting...")
    
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # Handlers
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(CommandHandler("postnow", cmd_postnow_meal))
    app.add_handler(CommandHandler("bounceland", cmd_bounceland))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("import", cmd_import))
    app.add_handler(CommandHandler("cancelimport", cmd_cancel_import))
    # Document handler for CSV import (only accepted after /import)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_for_import))

    # scheduler: weekly meal (Saturday 18:00 Europe/Berlin)
    scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
    scheduler.add_job(post_weekly_meal, trigger="cron", day_of_week=settings.meal_poll_day, hour=settings.meal_poll_hour, minute=settings.meal_poll_minute, args=[app])
    scheduler.start()

    await app.initialize()
    await app.start()

    try:
        await app.bot.send_message(chat_id=settings.chat_id, text="🤖 Bot started! Commands: /postnow (meal), /bounceland, /export, /import")
    except Exception as e:
        logging.warning(f"Could not send start message: {e}")

    logging.info("✅ Bot running (Polling mode)")
    # Run heartbeat and polling
    await asyncio.gather(heartbeat(), app.updater.start_polling())


if __name__ == "__main__":
    asyncio.run(main())
