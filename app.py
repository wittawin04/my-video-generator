import os
import re
import time
import random
import asyncio
import urllib.request
import numpy as np
import PIL.Image
from PIL import ImageDraw, ImageFont

# ปลั๊กอินแก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS สำหรับ MoviePy 1.0.3
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = getattr(PIL.Image, 'LANCZOS', PIL.Image.BICUBIC)

import streamlit as st
from google import genai
import edge_tts
import yt_dlp
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, AudioFileClip, concatenate_videoclips

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปอธิบายอัตโนมัติ")
st.write("สร้างคลิปสรุปเนื้อหา พร้อมเสียงพากย์และซับไตเติลภาษาไทยได้ทันที!")

# 1. ระบบดาวน์โหลดฟอนต์ภาษาไทยอัตโนมัติสำหรับทำซับไตเติล
FONT_PATH = "NotoSansThai.ttf"
if not os.path.exists(FONT_PATH):
    try:
        font_url = "https://github.com/google/fonts/raw/main/ofl/notosansthai/NotoSansThai-Regular.ttf"
        urllib.request.urlretrieve(font_url, FONT_PATH)
    except Exception:
        pass

# ดึง API Key จาก Streamlit Secrets
raw_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = str(raw_api_key).strip().strip('"').strip("'")

# ตัวเลือกการใช้งาน
option = st.radio("เลือกวิธีนำเข้าวิดีโอ:", ["อัปโหลดไฟล์วิดีโอ (.mp4)", "วางลิงก์ TikTok"])

uploaded_file = None
video_url = ""

if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
    uploaded_file = st.file_uploader("เลือกไฟล์วิดีโอจากเครื่อง (มือถือ/คอม):", type=["mp4", "mov"])
else:
    video_url = st.text_input("วางลิงก์ TikTok:")

aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])

# เพิ่มตัวเลือกความยาวสคริปต์/คลิป
duration_option = st.selectbox("เลือกความยาวสคริปต์และคลิป:", ["30 วินาที", "1 นาที", "2 นาที", "3 นาที", "5 นาที"])

# ฟังก์ชันดึงวิดีโอสำหรับ TikTok
def download_tiktok(url, output_path="input_video.mp4"):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'overwrites': True,
        'nocheckcertificate': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output_path

# ฟังก์ชันทำความสะอาดข้อความตัดสัญลักษณ์พิเศษออกก่อนส่งไปสร้างเสียงพากย์
def clean_text_for_tts(text):
    if not text:
        return "นี่คือวิดีโอสรุปเนื้อหาหลักครับ"
    text = re.sub(r'[\*\#\_\[\]\(\)\{\}\<\>]', '', text)
    text = re.sub(r'[^\w\s\d\.\,\!\?\u0E00-\u0E7F]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else "นี่คือวิดีโอสรุปเนื้อหาหลักครับ"

async def generate_tts(text, output_file="voice.mp3"):
    clean_text = clean_text_for_tts(text)
    voices = ["th-TH-NiwatNeural", "th-TH-PremwadeeNeural"]
    
    for voice in voices:
        try:
            communicate = edge_tts.Communicate(clean_text, voice)
            await communicate.save(output_file)
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return
        except Exception:
            continue
            
    raise Exception("ไม่สามารถสร้างไฟล์เสียงพากย์ได้ กรุณาลองใหม่อีกครั้ง")

# ฟังก์ชันสร้างซับไตเติลภาษาไทยด้วย Pillow + ฟอนต์ NotoSansThai
def create_subtitle_clip(text, target_w, target_h, duration):
    max_chars_per_line = 32 if target_w == 1080 else 55
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        if len(current_line) + len(word) + 1 <= max_chars_per_line:
            current_line = f"{current_line} {word}".strip()
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    if not lines:
        lines = [text]

    padding = 20
    line_height = 48
    box_h = len(lines) * line_height + (padding * 2)
    box_w = target_w - 80

    # สร้างกรอบดำโปร่งแสงรองหลังตัวหนังสือ
    img = PIL.Image.new("RGBA", (box_w, box_h), (0, 0, 0, 195))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, 34) if os.path.exists(FONT_PATH) else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    y = padding
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = max((box_w - text_w) // 2, 10)
        # ขอบดำตัวอักษรเพื่อความคมชัด
        draw.text((x, y), line, fill="white", font=font, stroke_width=2, stroke_fill="black")
        y += line_height

    img_np = np.array(img)
    clip = ImageClip(img_np).set_duration(duration)
    return clip.set_pos(('center', target_h - box_h - 70))

# ฟังก์ชันตัดสลับฉากวิดีโออัตโนมัติ (Dynamic Cut & Shuffle)
def create_dynamic_montage(clip, target_duration, chunk_duration=2.5):
    total_len = clip.duration
    subclips = []
    
    # หั่นวิดีโอต้นฉบับเป็นฉากย่อยๆ ฉากละประมาณ 2.5 วินาที
    t = 0.0
    while t < total_len:
        end_t = min(t + chunk_duration, total_len)
        if end_t - t >= 1.0: # เอาเฉพาะคลิปที่ยาวเกิน 1 วินาที
            subclips.append(clip.subclip(t, end_t))
        t += chunk_duration
        
    if not subclips:
        subclips = [clip]

    # สุ่มเลือกและสลับฉากต่อกันไปเรื่อยๆ จนยาวเท่ากับเสียงพากย์
    selected_clips = []
    accumulated_time = 0.0

    while accumulated_time < target_duration:
        shuffled = subclips.copy()
        random.shuffle(shuffled)
        for sc in shuffled:
            selected_clips.append(sc)
            accumulated_time += sc.duration
            if accumulated_time >= target_duration:
                break

    montage = concatenate_videoclips(selected_clips)
    return montage.subclip(0, target_duration)

if st.button("🚀 เริ่มสร้างวิดีโอ"):
    if not api_key:
        st.error("ไม่พบ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud ก่อนครับ")
    elif option == "วางลิงก์ TikTok" and not video_url:
        st.warning("กรุณาใส่ลิงก์วิดีโอก่อนครับ")
    elif option == "อัปโหลดไฟล์วิดีโอ (.mp4)" and not uploaded_file:
        st.warning("กรุณาเลือกไฟล์วิดีโอก่อนครับ")
    else:
        try:
            status = st.empty()
            video_file = "input_video.mp4"

            # 1. เตรียมไฟล์วิดีโอ
            if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
                status.info("📥 กำลังเตรียมไฟล์วิดีโอ...")
                with open(video_file, "wb") as f:
                    f.write(uploaded_file.read())
            else:
                status.info("📥 กำลังดาวน์โหลดวิดีโอ TikTok...")
                download_tiktok(video_url, video_file)
            
            # 2. คำนวณความยาวสคริปต์สไตล์ Storytelling
            duration_word_map = {
                "30 วินาที": ("30 วินาที", 70),
                "1 นาที": ("1 นาที", 140),
                "2 นาที": ("2 นาที", 280),
                "3 นาที": ("3 นาที", 420),
                "5 นาที": ("5 นาที", 700),
            }
            time_label, target_words = duration_word_map.get(duration_option, ("30 วินาที", 70))

            status.info(f"🤖 Gemini กำลังสร้างสคริปต์สไตล์ Storytelling ({time_label})...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = f"""
            คุณคือ Content Creator และนักเล่าเรื่องมืออาชีพ ช่วยวิเคราะห์วิดีโอนี้และสร้างสคริปต์พูดภาษาไทยความยาวประมาณ {time_label} (ประมาณ {target_words} คำ)

            แนวทางการเล่าเรื่อง:
            1. เล่าให้สนุกสนาน ตื่นเต้น มีจังหวะจะโคนสไตล์ Storytelling เล่าเนื้อหาว่าเรื่องราวในวิดีโอกำลังดำเนินไปอย่างไร
            2. อธิบายลำดับเหตุการณ์ให้ชัดเจน: จุดเริ่มต้นเกิดอะไรขึ้น -> ดำเนินเรื่องตื่นเต้นอย่างไร -> บทสรุปจบลงแบบไหน
            3. ใช้น้ำเสียงภาษาพูดที่เป็นธรรมชาติ ลื่นหู เป็นกันเอง เหมือนเพื่อนเล่าเรื่องสนุกๆ ให้ฟัง
            4. ตอบกลับเป็นข้อความเพรียวๆ สำหรับนำไปอ่านเป็นเสียงพากย์เท่านั้น ห้ามมีสัญลักษณ์พิเศษ (*, #) ห้ามมีวงเล็บคำอธิบาย
            """
            
            candidate_models = ['gemini-3.8-flash', 'gemini-2.5-flash']
            response = None
            quota_exceeded = False
            last_error = None
            
            for model_name in candidate_models:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=[g_file, prompt]
                    )
                    if response and getattr(response, 'text', None):
                        break
                except Exception as api_err:
                    last_error = api_err
                    err_msg = str(api_err)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        quota_exceeded = True
                        status.warning(f"⏳ โมเดล {model_name} โควตาเต็ม กำลังลองสลับโมเดลถัดไป...")
                        time.sleep(2)
                        continue
                    elif "404" in err_msg or "NOT_FOUND" in err_msg:
                        continue
                    elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                        time.sleep(3)
                        continue
                    else:
                        continue

            if not response or not getattr(response, 'text', None):
                if quota_exceeded:
                    raise Exception("โควตาฟรีประจำวันของ Gemini API Key นี้หมดแล้ว กรุณาสร้าง API Key ใหม่ใน Google AI Studio แล้วอัปเดตใน Streamlit Secrets ครับ")
                else:
                    raise Exception(f"ไม่สามารถเชื่อมต่อ Gemini API ได้: {str(last_error)}")

            script_text = response.text.strip()
            st.subheader("📝 สคริปต์การเล่าเรื่องที่ Gemini คิดให้:")
            st.write(script_text)

            # 3. เจนเสียงพากย์
            status.info("🎙️ กำลังสร้างเสียงพากย์ภาษาไทย...")
            asyncio.run(generate_tts(script_text, "voice.mp3"))

            # 4. ตัดสลับฉากวิดีโอและประกอบไฟล์
            status.info("🎞️ กำลังตัดสลับฉากวิดีโอและใส่ซับไตเติลภาษาไทย...")
            clip = VideoFileClip(video_file)
            audio = AudioFileClip("voice.mp3")
            
            # ตัดสลับฉากวิดีโอให้มีความยาวเท่าเสียงพากย์พอดี
            final_clip = create_dynamic_montage(clip, audio.duration, chunk_duration=2.5)
            final_clip = final_clip.set_audio(audio)
            
            target_w, target_h = (1080, 1920) if "แนวตั้ง" in aspect_ratio else (1920, 1080)
            final_clip = final_clip.resize(newsize=(target_w, target_h))

            # สร้างซับไตเติลภาษาไทยด้วยฟอนต์ NotoSansThai
            clean_script = clean_text_for_tts(script_text)
            txt_clip = create_subtitle_clip(clean_script, target_w, target_h, final_clip.duration)

            video_result = CompositeVideoClip([final_clip, txt_clip])
            output_filename = "output_video.mp4"
            video_result.write_videofile(output_filename, codec='libx264', audio_codec='aac')

            status.success("🎉 ทำคลิปเสร็จเรียบร้อยแล้ว!")
            st.video(output_filename)
            
            with open(output_filename, "rb") as file:
                st.download_button(
                    label="⬇️ ดาวน์โหลดวิดีโอ (.mp4)",
                    data=file,
                    file_name="summarized_story_video.mp4",
                    mime="video/mp4"
                )

        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {str(e)}")
