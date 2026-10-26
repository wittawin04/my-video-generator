import os
import time
import asyncio
import PIL.Image

# แก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS ให้ทำงานร่วมกับ MoviePy ได้
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

async def generate_tts(text, output_file="voice.mp3"):
    communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
    await communicate.save(output_file)

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
            
            # 2. ถอดความและคิดสคริปต์ด้วย Gemini 3.8 Flash
            status.info("🤖 Gemini กำลังวิเคราะห์วิดีโอและสร้างคำบรรยาย...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = """
            ช่วยวิเคราะห์วิดีโอนี้ และสร้างสคริปต์สรุปสั้นๆ ภาษาไทยสำหรับนำไปทำคลิปอธิบายความยาวไม่เกิน 30 วินาที
            ตอบกลับเป็นข้อความเพรียวๆ สำหรับนำไปอ่านเป็นเสียงพากย์ ไม่ต้องมีสัญลักษณ์พิเศษ หรือวงเล็บใดๆ
            """
            
            response = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = client.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=[g_file, prompt]
                    )
                    break
                except Exception as api_err:
                    if ("503" in str(api_err) or "UNAVAILABLE" in str(api_err)) and attempt < max_retries - 1:
                        status.warning(f"⏳ เซิร์ฟเวอร์ผู้ใช้แน่น กำลังลองใหม่อัตโนมัติครั้งที่ {attempt + 1}/{max_retries}...")
                        time.sleep(5)
                    else:
                        raise api_err

            # ตรวจสอบและป้องกันสคริปต์ว่างเปล่า
            script_text = ""
            if response and getattr(response, 'text', None):
                script_text = response.text.strip()
            
            if not script_text:
                script_text = "นี่คือวิดีโอสรุปเนื้อหาหลักที่ประมวลผลโดยระบบอัตโนมัติครับ"

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

            txt_clip = TextClip(script_text, fontsize=40, color='white', bg_color='black', method='caption', size=(target_w - 100, None))
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
