from flask import Flask, render_template, request, jsonify, send_from_directory
import threading
import time
import google.generativeai as genai
from gtts import gTTS
import os
import uuid
import atexit
import speech_recognition as sr
import io
from scipy.io.wavfile import write
import sounddevice as sd

app = Flask(__name__)

# Set up absolute path for audio directory
AUDIO_DIR = os.path.join(os.getcwd(),'mysite', 'static', 'audio')
if not os.path.exists(AUDIO_DIR):
    os.makedirs(AUDIO_DIR, exist_ok=True)

# Flag to stop conversation loop
stop_conversation_flag = False

# Global variables for conversation and audio queue
current_topic = ""
person1 = {}
person2 = {}
audio_queue = []  # Queue to store audio files for playback

# Initialize Google Generative AI (Gemini) API key
API_KEY = 'AIzaSyDmLjhtIezFvZFjGPa_l6POmiVEwoOqFmQ'  # Replace with your actual API key
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# List to track temporary .mp3 files
temp_files = []

# Conversation Generator using Google Generative AI
def generate_conversation(person1, person2, topic, person_s, question):
    prompt = f"Imagine a casual talk between {person1['name']} whose gender is {person1['gender']} and {person2['name']} whose gender is {person2['gender']} about {topic}. Now create a sentence for {person_s['name']} on replying to or providing an additional thing to {question} and the sentence should be less than 100 characters."
    try:
        response = model.generate_content([prompt])
        conversation = response.text.strip()  # Extracting the generated text
    except Exception as e:
        print(f"Error with Google Generative AI: {e}")
        conversation = "Error generating conversation. Please try again."

    print(f"Generated conversation: {conversation}")
    return conversation

# Function to convert text to speech using gTTS and save the audio file
def generate_audio(text):
    try:
        # Generate a unique filename for each audio file
        unique_filename = f"audio_{uuid.uuid4()}.mp3"
        file_path = os.path.join(AUDIO_DIR, unique_filename)
        print(f"Generating audio file at absolute path: {os.path.abspath(file_path)}")

        temp_files.append(file_path)  # Track the generated file

        # Generate speech with gTTS and save it
        tts = gTTS(text=text, lang='en')
        tts.save(file_path)
        #tts.save(os.path.join('mysite', file_path))

        # Double-check if the file was created successfully
        if os.path.exists(file_path):
            print(f"File saved successfully at: {file_path}")
            audio_queue.append(unique_filename)  # Add to the audio queue
        else:
            print(f"File failed to save at: {file_path}")

        return unique_filename
    except Exception as e:
        print(f"Error generating or saving speech: {e}")
        return None

# Speak conversation loop that continues until stopped
def speak_conversation_loop():
    global stop_conversation_flag, current_topic, person1, person2
    question = current_topic

    while not stop_conversation_flag:
        # Person 1's turn
        conversation = generate_conversation(person1, person2, current_topic, person1, question)
        audio_file = generate_audio(conversation)
        if audio_file:
            print(f"Audio file ready for person 1: {audio_file}")
        question = conversation
        time.sleep(5)  # Pause between conversation turns

        if stop_conversation_flag:
            break

        # Person 2's turn
        conversation = generate_conversation(person1, person2, current_topic, person2, question)
        audio_file = generate_audio(conversation)
        if audio_file:
            print(f"Audio file ready for person 2: {audio_file}")
        question = conversation
        time.sleep(5)  # Pause between conversation turns

@app.route('/')
def index():
    return render_template('index1.html')

@app.route('/start_conversation', methods=['POST'])
def start_conversation():
    global stop_conversation_flag, current_topic, person1, person2
    stop_conversation_flag = False

    person1 = {
        'name': request.form['person1_name'],
        'gender': request.form['person1_gender']
    }

    person2 = {
        'name': request.form['person2_name'],
        'gender': request.form['person2_gender']
    }

    current_topic = request.form['topic']

    # Start conversation in a new thread so the server continues running
    threading.Thread(target=speak_conversation_loop).start()

    return jsonify({'message': 'Conversation started'})

@app.route('/get_next_audio', methods=['GET'])
def get_next_audio():
    if audio_queue:
        # Get the next audio file from the queue
        next_audio = audio_queue.pop(0)
        print(f"Serving next audio file: {next_audio}")
        return jsonify({'audio_url': f"/audio/{next_audio}"})
    else:
        print("No audio file in queue")
        return jsonify({'audio_url': None})

@app.route('/stop_conversation', methods=['POST'])
def stop_conversation():
    global stop_conversation_flag
    stop_conversation_flag = True
    cleanup_temp_files()
    return jsonify({'message': 'Conversation stopped'})

@app.route('/audio/<filename>')
def serve_audio(filename):
    """Serve the generated audio file to the client."""
    return send_from_directory(AUDIO_DIR, filename)

@app.route('/input_voice', methods=['POST'])
def input_voice():
    recognizer = sr.Recognizer()
    sample_rate = 16000
    duration = 5  # Record for 5 seconds

    # Record audio
    print("Recording audio... Speak now!")
    audio_data = sd.rec(int(sample_rate * duration), samplerate=sample_rate, channels=1, dtype='int16')
    sd.wait()  # Wait until recording is complete
    print("Recording complete!")

    # Save the audio to a BytesIO stream
    wav_io = io.BytesIO()
    write(wav_io, sample_rate, audio_data)

    wav_io.seek(0)  # Reset stream position for reading
    audio_file = sr.AudioFile(wav_io)

    with audio_file as source:
        audio = recognizer.record(source)

    try:
        new_topic = recognizer.recognize_google(audio)
        print(f"Recognized topic: {new_topic}")

        # Update the global topic and restart the conversation
        update_topic(new_topic)

        return jsonify({'topic': new_topic})
    except sr.UnknownValueError:
        return jsonify({'error': 'Could not understand audio'}), 400
    except sr.RequestError as e:
        return jsonify({'error': f"Request error: {e}"}), 500


# Function to update the topic and restart the conversation
def update_topic(new_topic):
    global stop_conversation_flag, current_topic

    # Stop the current conversation loop
    stop_conversation_flag = True

    # Update the topic
    current_topic = new_topic

    # Restart the conversation with the new topic after a small delay
    time.sleep(1)  # Give a little time for the current thread to exit
    stop_conversation_flag = False

    # Start the new conversation loop in a new thread
    threading.Thread(target=speak_conversation_loop).start()



def cleanup_temp_files():
    for file in temp_files:
        try:
            if os.path.exists(file):
                os.remove(file)
                print(f"Deleted: {file}")
        except Exception as e:
            print(f"Error deleting {file}: {e}")

atexit.register(cleanup_temp_files)

if __name__ == '__main__':
    app.run(port=5005)
