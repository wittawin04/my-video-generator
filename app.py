import os
import re
import time
import asyncio
import PIL.Image

# 1. ปลดล็อกระบบความปลอดภัยของ ImageMagick บน Streamlit Cloud ให้สร้าง TextClip ได้
os.makedirs("/tmp/magick", exist_ok=True)
with open("/tmp/magick/policy.xml", "w") as f:
    f.write('<policymap><policy domain="path" rights="read | write" pattern="@*"/></policymap>')
os.environ["MAGICK_CONFIGURE_PATH"] = "/tmp/magick"

# 2. แก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS ให้ทำงานร่วมกับ MoviePy ได้
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = getattr(PIL.Image, 'LANCZOS', PIL.Image.BICUBIC)

import streamlit as st
from google import genai
import edge_tts
import yt_dlp
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปอธิบายอัตโนมัติ")
st.write("สร้างคลิปสรุปเนื้อหา พร้อมเสียงพากย์และซับไตเติลภาษาไทยได้ทันที!")

# ดึง API Key จาก Streamlit Secrets
api_key = st.secrets.get("GEMINI_API_KEY", "")

# ตัวเลือกรองรับการใช้งาน
option = st.radio("เลือกวิธีนำเข้าวิดีโอ:", ["อัปโหลดไฟล์วิดีโอ (.mp4)", "วางลิงก์ TikTok"])

uploaded_file = None
video_url = ""

if option == "อัปโหลดไฟล์วิดีโอ (.mp4)":
    uploaded_file = st.file_uploader("เลือกไฟล์วิดีโอจากเครื่อง (มือถือ/คอม):", type=["mp4", "mov"])
else:
    video_url = st.text_input("วางลิงก์ TikTok:")

aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])

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
            
            # 2. ถอดความและคิดสคริปต์ด้วย Gemini (พร้อมระบบ Fallback สลับโมเดลอัตโนมัติ)
            status.info("🤖 Gemini กำลังวิเคราะห์วิดีโอและสร้างคำบรรยาย...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = """
            ช่วยวิเคราะห์วิดีโอนี้ และสร้างสคริปต์สรุปสั้นๆ ภาษาไทยสำหรับนำไปทำคลิปอธิบายความยาวไม่เกิน 30 วินาที
            ตอบกลับเป็นข้อความเพรียวๆ สำหรับนำไปอ่านเป็นเสียงพากย์ ไม่ต้องมีสัญลักษณ์พิเศษ หรือวงเล็บใดๆ
            """
            
            # รายชื่อโมเดลที่ต้องการสลับใช้งานกรณีโมเดลหลักโควตาเต็ม (429)
            candidate_models = ['gemini-3.8-flash', 'gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
            response = None
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
                        status.warning(f"⏳ โมเดล {model_name} โควตาเต็ม กำลังสลับไปใช้โมเดลสำรอง...")
                        time.sleep(2)
                        continue
                    elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                        time.sleep(3)
                        continue
                    else:
                        continue

            if not response or not getattr(response, 'text', None):
                if "429" in str(last_error) or "RESOURCE_EXHAUSTED" in str(last_error):
                    raise Exception("โควตาฟรีประจำวันของ Gemini API Key นี้หมดแล้ว กรุณาเปลี่ยน API Key ใหม่ใน Streamlit Secrets ครับ")
                else:
                    raise Exception(f"ไม่สามารถเชื่อมต่อ Gemini API ได้: {str(last_error)}")

            script_text = response.text.strip()
            st.subheader("📝 สคริปต์ที่ Gemini คิดให้:")
            st.write(script_text)

            # 3. เจนเสียงพากย์
            status.info("🎙️ กำลังสร้างเสียงพากย์ภาษาไทย...")
            asyncio.run(generate_tts(script_text, "voice.mp3"))

            # 4. ประกอบวิดีโอ
            status.info("🎞️ กำลังตัดต่อและใส่ซับไตเติล...")
            clip = VideoFileClip(video_file)
            audio = AudioFileClip("voice.mp3")
            
            min_duration = min(clip.duration, audio.duration)
            final_clip = clip.subclip(0, min_duration)
            final_clip = final_clip.set_audio(audio)
            
            target_w, target_h = (1080, 1920) if "แนวตั้ง" in aspect_ratio else (1920, 1080)
            final_clip = final_clip.resize(newsize=(target_w, target_h))

            clean_script = clean_text_for_tts(script_text)
            txt_clip = TextClip(clean_script, fontsize=40, color='white', bg_color='black', method='caption', size=(target_w - 100, None))
            txt_clip = txt_clip.set_pos(('center', 'bottom')).set_duration(final_clip.duration)

            video_result = CompositeVideoClip([final_clip, txt_clip])
            output_filename = "output_video.mp4"
            video_result.write_videofile(output_filename, codec='libx264', audio_codec='aac')

            status.success("🎉 ทำคลิปเสร็จเรียบร้อยแล้ว!")
            st.video(output_filename)
            
            with open(output_filename, "rb") as file:
                st.download_button(
                    label="⬇️ ดาวน์โหลดวิดีโอ (.mp4)",
                    data=file,
                    file_name="summarized_video.mp4",
                    mime="video/mp4"
                )

        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {str(e)}")
