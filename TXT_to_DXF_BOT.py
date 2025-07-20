import os
import tempfile
import chardet
import csv
import pandas as pd
import ezdxf
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import logging

# Включаем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Определяем состояния диалога
STATE_FILE, STATE_MAPPING = range(2)

def detect_delimiter(line: str) -> str:
    """Определяет разделитель по первой непустой строке."""
    if "\t" in line:
        return "\t"
    elif ", " in line:
        return ", "
    elif "," in line:
        return ","
    else:
        return " "  # по умолчанию пробел

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Привет! Отправьте мне текстовый файл с данными (как документ *.txt).")
    return STATE_FILE

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    document = update.message.document
    if not document:
        await update.message.reply_text("Пожалуйста, отправьте файл как документ.")
        return STATE_FILE

    # Скачиваем файл во временную директорию
    file = await document.get_file()
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, document.file_name)
    await file.download_to_drive(custom_path=file_path)
    context.user_data["file_path"] = file_path

    # Определяем кодировку файла
    with open(file_path, "rb") as f:
        raw_data = f.read(10000)
    result_encoding = chardet.detect(raw_data)
    encoding = result_encoding.get("encoding", "utf-8")
    if encoding.lower() == "ascii":
        encoding = "cp1251"
    context.user_data["encoding"] = encoding

    # Определяем разделитель по первой непустой строке
    with open(file_path, "r", encoding=encoding) as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                delimiter = detect_delimiter(stripped)
                logger.info(f"Определён разделитель: {repr(delimiter)}")
                break

    # Читаем файл с помощью csv.reader
    lines = []
    with open(file_path, "r", encoding=encoding) as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            # Убираем возможные пустые строки и очищаем каждое поле
            row = [cell.strip() for cell in row if cell.strip() != ""]
            if len(row) < 5:
                continue
            lines.append(row)

    if not lines:
        await update.message.reply_text("Файл не содержит достаточных данных.")
        return ConversationHandler.END

    # Создаем DataFrame с исходными данными
    data_initial = pd.DataFrame(lines)
    context.user_data["data_initial"] = data_initial
    ncols = data_initial.shape[1]
    await update.message.reply_text(
        f"Ваш файл содержит {ncols} колонок.\n"
        "Выберите вариант соответствия:\n"
        "1 — Стандартное соответствие: Point, X, Y, Z, Code\n"
        "2 — Перестановка X и Y: Point, Y, X, Z, Code\n"
        "Отправьте цифру 1 или 2."
    )
    return STATE_MAPPING

async def handle_mapping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    default_mapping = {"Point": 0, "X": 1, "Y": 2, "Z": 3, "Code": 4}
    swapped_mapping = {"Point": 0, "Y": 1, "X": 2, "Z": 3, "Code": 4}
    if text == "1":
        mapping = default_mapping
    elif text == "2":
        mapping = swapped_mapping
    else:
        await update.message.reply_text("Пожалуйста, отправьте 1 или 2.")
        return STATE_MAPPING

    context.user_data["mapping"] = mapping

    # Формирование итогового DataFrame
    data_initial = context.user_data["data_initial"]
    mapping = context.user_data["mapping"]
    final_rows = []
    for i, row in data_initial.iterrows():
        tokens = list(row.dropna().astype(str))
        if len(tokens) < 5:
            continue
        point = tokens[mapping["Point"]]
        x = tokens[mapping["X"]]
        y = tokens[mapping["Y"]]
        z = tokens[mapping["Z"]]
        code = tokens[mapping["Code"]]
        max_required = max(mapping.values())
        comments = " ".join(tokens[max_required + 1:]) if len(tokens) > max_required + 1 else ""
        final_rows.append([point, x, y, z, code, comments])
    final_data = pd.DataFrame(final_rows, columns=["Point", "X", "Y", "Z", "Code", "Coments"])
    context.user_data["final_data"] = final_data
    await update.message.reply_text("Данные успешно обработаны. Генерирую DXF-файл...")

    # Создание DXF-файла
    doc = ezdxf.new(dxfversion="R2018")
    msp = doc.modelspace()
    layers_colors = {
        "Points": 7,
        "Codes": 200,
        "Numbers": 10,
        "Elevations": 34,
        "Comments": 250,
    }
    for name, color in layers_colors.items():
        if name in doc.layers:
            doc.layers.get(name).dxf.color = color
        else:
            doc.layers.new(name=name, dxfattribs={"color": color})
    if "Simplex" not in doc.styles:
        doc.styles.new("Simplex", dxfattribs={"font": "simplex.shx"})
    number_offset = (0.5, 1.5)
    code_offset = (0.5, -1.5)
    elevation_offset = (0.5, 0)
    comment_offset = (0.5, -3.0)
    final_data = context.user_data["final_data"]
    num_rows = len(final_data)
    for j in range(num_rows):
        try:
            try:
                x = float(final_data.loc[j, "X"])
                y = float(final_data.loc[j, "Y"])
                z = float(final_data.loc[j, "Z"])
            except ValueError:
                comment_text = " ".join(final_data.loc[j].astype(str))
                comment_entity = msp.add_text(
                    comment_text,
                    dxfattribs={"layer": "Comments", "height": 0.5, "style": "Simplex"},
                )
                comment_entity.dxf.insert = (0, 0)
                continue

            msp.add_point((x, y, z), dxfattribs={"layer": "Points"})
            
            point_text = str(final_data.loc[j, "Point"])
            text_entity = msp.add_text(
                point_text,
                dxfattribs={"layer": "Numbers", "height": 0.5, "style": "Simplex"},
            )
            text_entity.dxf.insert = (x + number_offset[0], y + number_offset[1])
            
            code_text = str(final_data.loc[j, "Code"])
            code_entity = msp.add_text(
                code_text,
                dxfattribs={"layer": "Codes", "height": 0.5, "style": "Simplex"},
            )
            code_entity.dxf.insert = (x + code_offset[0], y + code_offset[1])
            
            elevation_text = str(final_data.loc[j, "Z"])
            elevation_entity = msp.add_text(
                elevation_text,
                dxfattribs={"layer": "Elevations", "height": 0.5, "style": "Simplex"},
            )
            elevation_entity.dxf.insert = (x + elevation_offset[0], y + elevation_offset[1])
            
            comment_text = str(final_data.loc[j, "Coments"]).strip()
            if comment_text:
                comment_entity = msp.add_text(
                    comment_text,
                    dxfattribs={"layer": "Comments", "height": 0.5, "style": "Simplex"},
                )
                comment_entity.dxf.insert = (x + comment_offset[0], y + comment_offset[1])
        except Exception as e:
            logger.error(f"Ошибка при обработке точки {j}: {e}")
            continue

    # Сохраняем DXF-файл во временную директорию и отправляем его пользователю
    temp_dir = tempfile.mkdtemp()
    dxf_path = os.path.join(temp_dir, "output.dxf")
    doc.saveas(dxf_path)
    with open(dxf_path, "rb") as f:
        dxf_data = f.read()
    from io import BytesIO
    bio = BytesIO(dxf_data)
    bio.name = "output.dxf"
    await update.message.reply_document(document=InputFile(bio), filename="output.dxf")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

def main():
    BOT_TOKEN = "8181272115:AAE_ahXEME1nk3s7OA-dFiv6QM1ojnXMGHE"  # Замените на токен вашего бота
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Document.ALL, handle_file)
        ],
        states={
            STATE_FILE: [MessageHandler(filters.Document.ALL, handle_file)],
            STATE_MAPPING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mapping)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
