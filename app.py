import os
import asyncio
import streamlit as st
from google import genai
import yt_dlp
import edge_tts
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปอธิบายอัตโนมัติ")
st.write("วางลิงก์วิดีโอ สรุปเนื้อหา และสร้างคลิปพร้อมคำบรรยายได้ทันที!")

# ดึง API Key จาก Streamlit Secrets
api_key = st.secrets.get("GEMINI_API_KEY", "")

video_url = st.text_input("วางลิงก์วิดีโอ (TikTok, YouTube Shorts ฯลฯ):")
aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])

def download_video(url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': 'input_video.mp4',
        'overwrites': True,
        'nocheckcertificate': True,
        # จำลองการส่งคำขอแบบ Android App เพื่อหลีกเลี่ยงการตรวจจับ Bot จาก YouTube
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return "input_video.mp4"

async def generate_tts(text, output_file="voice.mp3"):
    communicate = edge_tts.Communicate(text, "th-TH-NiwatNeural")
    await communicate.save(output_file)

if st.button("🚀 เริ่มสร้างวิดีโอ"):
    if not api_key:
        st.error("ไม่พบ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud ก่อนครับ")
    elif not video_url:
        st.warning("กรุณาใส่ลิงก์วิดีโอก่อนครับ")
    else:
        try:
            status = st.empty()
            
            # 1. ดาวน์โหลดวิดีโอ
            status.info("📥 กำลังดาวน์โหลดวิดีโอต้นทาง...")
            video_file = download_video(video_url)
            
            # 2. ถอดความและคิดสคริปต์ด้วย Gemini
            status.info("🤖 Gemini กำลังวิเคราะห์วิดีโอและสร้างคำบรรยาย...")
            client = genai.Client(api_key=api_key)
            uploaded_file = client.files.upload(file=video_file)
            
            prompt = """
            ช่วยวิเคราะห์วิดีโอนี้ และสร้างสคริปต์สรุปสั้นๆ ภาษาไทยสำหรับนำไปทำคลิปอธิบายความยาวไม่เกิน 30 วินาที
            ตอบกลับเป็นข้อความเพรียวๆ สำหรับนำไปอ่านเป็นเสียงพากย์ ไม่ต้องมีสัญลักษณ์พิเศษ
            """
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[uploaded_file, prompt]
            )
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
            
            final_clip = clip.subclip(0, min(clip.duration, audio.duration))
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
