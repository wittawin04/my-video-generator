import os
import asyncio
import requests
import streamlit as st
from google import genai
import edge_tts
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปอธิบายอัตโนมัติ")
st.write("วางลิงก์วิดีโอ (YouTube, TikTok, IG) ระบบจะไปดึงไฟล์มาสรุป และใส่เสียงพากย์พร้อมคำบรรยายให้อัตโนมัติ!")

# ดึง API Key จาก Streamlit Secrets
api_key = st.secrets.get("GEMINI_API_KEY", "")

video_url = st.text_input("วางลิงก์วิดีโอ (YouTube, TikTok, Reels ฯลฯ):")
aspect_ratio = st.selectbox("เลือกขนาดวิดีโอ:", ["แนวตั้ง (9:16)", "แนวนอน (16:9)"])

# ฟังก์ชันดึงไฟล์วิดีโอผ่าน Cobalt API (ไม่ติดบล็อก IP)
def download_video_via_api(url, output_path="input_video.mp4"):
    cobalt_api = "https://api.cobalt.tools/"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {"url": url}
    
    response = requests.post(cobalt_api, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    video_download_url = None
    if data.get("status") in ["tunnel", "redirect"]:
        video_download_url = data.get("url")
    elif data.get("status") == "picker" and data.get("picker"):
        video_download_url = data["picker"][0].get("url")
        
    if not video_download_url:
        error_text = data.get("text", "ไม่สามารถดึงวิดีโอจากลิงก์นี้ได้")
        raise Exception(f"API Error: {error_text}")
        
    # โหลดไฟล์วิดีโอ MP4 จากลิงก์ตรงที่ได้มา
    res = requests.get(video_download_url, stream=True, timeout=60)
    res.raise_for_status()
    
    with open(output_path, "wb") as f:
        for chunk in res.iter_content(chunk_size=8192):
            f.write(chunk)
            
    return output_path

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
            
            # 1. ดาวน์โหลดวิดีโอผ่าน Cobalt API
            status.info("🌐 กำลังส่งลิงก์ไปให้ระบบดาวน์โหลดไฟล์วิดีโอ...")
            video_file = download_video_via_api(video_url)
            
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
