import os
import re
import time
import json
import asyncio
import numpy as np
import PIL.Image
from gtts import gTTS

# ปลั๊กอินแก้ปัญหา Pillow v10+ ยกเลิกคำว่า ANTIALIAS สำหรับ MoviePy 1.0.3
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = getattr(PIL.Image, 'LANCZOS', PIL.Image.BICUBIC)

import streamlit as st
from google import genai
import edge_tts
import yt_dlp
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips

st.set_page_config(page_title="Auto Video Generator", page_icon="🎬", layout="centered")
st.title("🎬 เครื่องมือสร้างคลิปอธิบายอัตโนมัติ")
st.write("สร้างคลิปสรุปเนื้อหา ตัดฉากตรงตาม Timestamp ภาพ พร้อมเสียงพากย์ฟรี!")

# ดึง API Key จาก Streamlit Secrets
raw_api_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = str(raw_api_key).strip().strip('"').strip("'")

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

# ตัวเลือกเสียงพากย์ฟรี
voice_engine = st.selectbox(
    "เลือกโมเดลเสียงพากย์ฟรี (Free Voice Model):", 
    [
        "Google Voice (gTTS - สำเนียงไทยอ่านชัด แม่นยำ ฟรี 100%)",
        "Edge Voice ผู้หญิง (Premwadee - เสียงลื่นหู ฟรี)",
        "Edge Voice ผู้ชาย (Niwat - เสียงนุ่มลึก ฟรี)"
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

# ฟังก์ชันจัดข้อความและเว้นวรรคเพื่อให้ AI อ่านไทยได้ถูกต้องที่สุด
def clean_text_for_tts(text):
    if not text:
        return "นี่คือวิดีโอสรุปเนื้อหาหลักครับ"
    text = re.sub(r'[\*\#\_\[\]\(\)\{\}\<\>]', '', text)
    text = re.sub(r'([\.\,\!\?])', r'\1 ', text)
    text = re.sub(r'[^\w\s\u0E00-\u0E7F]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if text else "นี่คือวิดีโอสรุปเนื้อหาหลักครับ"

# ฟังก์ชันสร้างเสียงพากย์รองรับทั้ง gTTS และ Edge-TTS
def generate_tts_free(text, engine_choice, output_file="voice.mp3"):
    clean_text = clean_text_for_tts(text)
    
    if "Google Voice" in engine_choice:
        tts = gTTS(text=clean_text, lang='th', slow=False)
        tts.save(output_file)
    else:
        voice_code = "th-TH-PremwadeeNeural" if "Premwadee" in engine_choice else "th-TH-NiwatNeural"
        async def run_edge():
            communicate = edge_tts.Communicate(clean_text, voice_code)
            await communicate.save(output_file)
        asyncio.run(run_edge())

if st.button("🚀 เริ่มสร้างวิดีโอ"):
    if not api_key:
        st.error("ไม่พบ GEMINI_API_KEY ในระบบ Secrets กรุณาตั้งค่าใน Streamlit Cloud ก่อนครับ")
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
            
            # 2. ตั้งค่าเวลาและสร้างสคริปต์แยกตาม Timestamp
            duration_word_map = {
                "30 วินาที": ("30 วินาที", 65),
                "1 นาที": ("1 นาที", 130),
                "2 นาที": ("2 นาที", 260),
                "3 นาที": ("3 นาที", 390),
                "5 นาที": ("5 นาที", 650),
            }
            time_label, target_words = duration_word_map.get(duration_option, ("30 วินาที", 65))

            status.info(f"🤖 Gemini กำลังวิเคราะห์ Timestamp ภาพและสร้างสคริปต์พากย์ ({time_label})...")
            client = genai.Client(api_key=api_key)
            g_file = client.files.upload(file=video_file)
            
            prompt = f"""
            ช่วยวิเคราะห์วิดีโอนี้ แบ่งวิดีโอออกเป็นฉากๆ ตามช่วงเวลาจริง (Timestamp ในรูปแบบวินาที) และเขียนสคริปต์พากย์ภาษาไทยให้ตรงกับภาพของแต่ละฉาก
            ความยาวรวมประมาณ {time_label} (ประมาณ {target_words} คำ)

            ตอบกลับในรูปแบบ JSON Array เท่านั้น ห้ามมีข้อความอื่นนอกเหนือจาก JSON เช่น:
            [
              {{"start_sec": 0, "end_sec": 5, "text": "เปิดเรื่องมาจะเห็นว่า..."}},
              {{"start_sec": 6, "end_sec": 12, "text": "จากนั้นฉากนี้เกิดอะไรขึ้น..."}}
            ]

            กฎเหล็กสำหรับฟิลด์ "text":
            1. สคริปต์พากย์ต้องตรงกับภาพที่เกิดในช่วง start_sec ถึง end_sec นั้นๆ
            2. เขียนด้วยภาษาพูดไทยที่สะกดตรงตัว อ่านง่าย ไม่ใช้คำทับศัพท์อังกฤษ (เช่น TikTok -> ติ๊กต็อก)
            3. เว้นวรรคประโยคให้ชัดเจน ห้ามมีอักขระพิเศษ (*, #) หรือวงเล็บ
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

            raw_response_text = response.text.strip()
            # ทำความสะอาดสตริงเอา JSON Block ออก
            clean_json_str = re.sub(r'```json\s*|\s*```', '', raw_response_text).strip()
            
            scenes = []
            try:
                scenes = json.loads(clean_json_str)
            except Exception:
                # กรณี Gemini ตอบกลับไม่อยู่ในฟอร์แมต JSON ให้จัดกลุ่มเป็นฉากเดียว
                scenes = [{"start_sec": 0, "end_sec": 30, "text": raw_response_text}]

            # แสดงสคริปต์ที่แบ่งตามฉากให้ผู้ใช้ดู
            st.subheader("📝 สคริปต์และการตัดฉากที่ Gemini วิเคราะห์ได้:")
            full_script_display = ""
            for i, sc in enumerate(scenes, 1):
                full_script_display += f"**ฉากที่ {i} [{sc.get('start_sec', 0)}s - {sc.get('end_sec', 0)}s]:** {sc.get('text', '')}\n\n"
            st.markdown(full_script_display)

            # 3. ตัดคลิปตาม Timestamp และสร้างเสียงพากย์ฉากต่อฉาก
            status.info("🎞️ กำลังตัดวิดีโอตาม Timestamp และรวมเสียงพากย์แต่ละฉาก...")
            main_clip = VideoFileClip(video_file)
            scene_clips = []

            for idx, sc in enumerate(scenes):
                text = sc.get('text', '')
                if not text.strip():
                    continue

                start_t = float(sc.get('start_sec', 0))
                end_t = float(sc.get('end_sec', start_t + 5))

                # ป้องกันเวลาเกินความยาวจริงของไฟล์วิดีโอ
                start_t = max(0.0, min(start_t, main_clip.duration - 0.5))
                end_t = max(start_t + 0.5, min(end_t, main_clip.duration))

                # สร้างไฟล์เสียงพากย์เฉพาะฉากนี้
                audio_file = f"voice_scene_{idx}.mp3"
                generate_tts_free(text, voice_engine, audio_file)
                sc_audio = AudioFileClip(audio_file)

                # ตัดคลิปช่วงเวลานั้นๆ
                sc_video = main_clip.subclip(start_t, end_t)

                # ปรับความยาวของวิดีโอฉากนั้นให้พอดีกับความยาวของเสียงพากย์
                if sc_video.duration < sc_audio.duration:
                    n_repeats = int(np.ceil(sc_audio.duration / sc_video.duration))
                    sc_video = concatenate_videoclips([sc_video] * n_repeats).subclip(0, sc_audio.duration)
                else:
                    sc_video = sc_video.subclip(0, sc_audio.duration)

                sc_video = sc_video.set_audio(sc_audio)
                scene_clips.append(sc_video)

            if not scene_clips:
                raise Exception("ไม่สามารถตัดแบ่งฉากวิดีโอได้ กรุณาลองใหม่อีกครั้ง")

            # รวมคลิปทุกฉากเข้าด้วยกัน
            final_clip = concatenate_videoclips(scene_clips)
            
            target_w, target_h = (1080, 1920) if "แนวตั้ง" in aspect_ratio else (1920, 1080)
            final_clip = final_clip.resize(newsize=(target_w, target_h))

            output_filename = "output_video.mp4"
            final_clip.write_videofile(output_filename, codec='libx264', audio_codec='aac')

            status.success("🎉 ทำคลิปเสร็จเรียบร้อยแล้ว!")
            st.video(output_filename)
            
            with open(output_filename, "rb") as file:
                st.download_button(
                    label="⬇️ ดาวน์โหลดวิดีโอ (.mp4)",
                    data=file,
                    file_name="summarized_synced_video.mp4",
                    mime="video/mp4"
                )

        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {str(e)}")
