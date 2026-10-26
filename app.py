import os
import re
import time
import json
import requests
import numpy as np
import PIL.Image

# ปลั๊กอินแก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS สำหรับ MoviePy 1.0.3
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = getattr(PIL.Image, 'LANCZOS', PIL.Image.BICUBIC)

import streamlit as st
from google import genai
import yt_dlp
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปเล่าเรื่องตัดฉากอัตโนมัติ (ElevenLabs Only)")
st.write("สรุปวิดีโอ เล่าเรื่องสนุก ตัดฉากตรงภาพ พากย์เสียงเนียนระดับมนุษย์ด้วย ElevenLabs!")

# ดึง API Key จาก Streamlit Secrets
raw_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = str(raw_api_key).strip().strip('"').strip("'")
eleven_api_key = st.secrets.get("ELEVENLABS_API_KEY", "").strip().strip('"').strip("'")

# ตัวเลือกนำเข้าวิดีโอ
option = st.radio("เลือกวิธีนำเข้าวิดีโอ:", ["อัปโหลดไฟล์วิดีโอ (.mp4)", "วางลิงก์ TikTok"])

uploaded_file = None
video_url = ""

if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
    uploaded_file = st.file_uploader("เลือกไฟล์วิดีโอจากเครื่อง (มือถือ/คอม):", type=["mp4", "mov"])
else:
    video_url = st.text_input("วางลิงก์ TikTok:")

aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])
duration_option = st.selectbox("เลือกความยาวสคริปต์และคลิป:", ["30 วินาที", "1 นาที", "2 นาที", "3 นาที", "5 นาที"])

# ตัวเลือกเสียง ElevenLabs เท่านั้น
voice_selection = st.selectbox(
    "เลือกเสียงพากย์ ElevenLabs:", 
    [
        "Adam (เสียงชาย - นุ่มลึก มีเสน่ห์ เล่าเรื่องปั่นๆ)",
        "Rachel (เสียงหญิง - สดใส มีพลัง เล่าสนุก)",
        "Charlie (เสียงชาย - กระฉับกระเฉง สายสปอยล์คลิป)"
    ]
)

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

# ฟังก์ชันแปลงคำอ่านภาษาอังกฤษเป็นภาษาไทยให้ AI อ่านเป๊ะ
def clean_text_for_tts(text):
    if not text:
        return "มาดูคลิปนี้กันครับ"
    
    word_map = {
        "Mr. Crab": "มิสเตอร์แครปส์",
        "Mr.Crab": "มิสเตอร์แครปส์",
        "Mr. Krabs": "มิสเตอร์แครปส์",
        "SpongeBob": "สปอนจ์บอบ",
        "Patrick": "แพทริก",
        "TikTok": "ติ๊กต็อก",
        "Facebook": "เฟซบุ๊ก",
        "YouTube": "ยูทูบ"
    }
    
    for k, v in word_map.items():
        text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
        
    text = re.sub(r'[\*\#\_\[\]\(\)\{\}\<\>]', '', text)
    text = re.sub(r'([\.\,\!\?])', r'\1 ', text)
    text = re.sub(r'[^\w\s\u0E00-\u0E7F]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else "มาดูคลิปนี้กันครับ"

# ฟังก์ชันสร้างเสียงพากย์ด้วย ElevenLabs API โดยตรง
def generate_voice_elevenlabs(text, choice, output_file="voice.mp3"):
    if not eleven_api_key:
        raise Exception("ไม่พบ ELEVENLABS_API_KEY ใน Streamlit Secrets กรุณาใส่ API Key ใน Secrets ก่อนใช้งานครับ")

    clean_text = clean_text_for_tts(text)

    # Voice ID มาตรฐานของ ElevenLabs
    voice_id = "pNInz6obpgDQGcFmaJgB" # Adam Default
    if "Rachel" in choice:
        voice_id = "21m00Tcm4TlvDq8ikWAM"
    elif "Charlie" in choice:
        voice_id = "IKne3meq5aSn9XLyUdCD"

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": eleven_api_key
    }
    payload = {
        "text": clean_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }
    
    res = requests.post(url, json=payload, headers=headers, timeout=30)
    if res.status_code == 200 and len(res.content) > 500:
        with open(output_file, "wb") as f:
            f.write(res.content)
    else:
        raise Exception(f"เกิดข้อผิดพลาดจาก ElevenLabs API (Status Code: {res.status_code}): {res.text}")

if st.button("🚀 เริ่มสร้างวิดีโอ"):
    if not api_key:
        st.error("ไม่พบ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud ก่อนครับ")
    elif not eleven_api_key:
        st.error("ไม่พบ ELEVENLABS_API_KEY ในระบบ Secrets กรุณาตั้งค่าก่อนใช้งานครับ")
    elif option == "วางลิงก์ TikTok" and not video_url:
        st.warning("กรุณาใส่ลิงก์วิดีโอก่อนครับ")
    elif option == "อัปโหลดไฟล์วิดีโอ (.mp4)" and not uploaded_file:
        st.warning("กรุณาเลือกไฟล์วิดีโอจากเครื่องก่อนครับ")
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
            
            # 2. ตั้งค่าเวลาและสร้างสคริปต์
            duration_word_map = {
                "30 วินาที": ("30 วินาที", 75),
                "1 นาที": ("1 นาที", 150),
                "2 นาที": ("2 นาที", 300),
                "3 นาที": ("3 นาที", 450),
                "5 นาที": ("5 นาที", 750),
            }
            time_label, target_words = duration_word_map.get(duration_option, ("30 วินาที", 75))

            status.info(f"🤖 Gemini กำลังวิเคราะห์ Timestamp ภาพและสร้างสคริปต์พากย์ ({time_label})...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = f"""
            สวมบทบาทเป็น "ครีเอเตอร์สายเล่าเรื่องสุดปั่น" ที่กำลังเล่าคลิปนี้ให้เพื่อนฟังแบบตื่นเต้นและใส่อารมณ์สุดๆ!
            แบ่งเนื้อหาออกเป็นฉากตาม Timestamp จริงในวิดีโอ ความยาวรวมประมาณ {time_label} (ประมาณ {target_words} คำ)

            ตอบกลับในรูปแบบ JSON Array เท่านั้น ห้ามมีข้อความอื่นนอกเหนือจาก JSON เช่น:
            [
              {{"start_sec": 0, "end_sec": 5, "text": "เฮ้ยทุกคน ดูช็อตนี้! เปิดมาก็เอาเลยว่ะ..."}},
              {{"start_sec": 6, "end_sec": 12, "text": "จังหวะนี้แหละ อย่างพีค..."}}
            ]

            กฎเหล็กการแต่งบทพากย์ ("text"):
            1. ใช้น้ำเสียงแบบเพื่อนเล่าเรื่องให้เพื่อนฟัง มีคำอุทานสร้างอารมณ์ เช่น "เฮ้ย!", "ว้าว!", "ดูสิ!", "จังหวะนี้คือ!"
            2. เขียนชื่อตัวละครเป็นคำอ่านไทยตรงตัว เช่น Mr. Krabs -> มิ
