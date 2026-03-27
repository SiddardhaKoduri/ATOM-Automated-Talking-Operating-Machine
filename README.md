# ATOM-Automated-Talking-Operating-Machine
ATOM: Autonomous Task & Operations ModuleATOM is a voice-controlled AI assistant integrated with Arduino to bridge the gap between software intelligence and hardware control. It features natural language processing, real-time translation, and direct robotic command execution.
**🚀 Features**
**🎙️ Voice CommandsSystem Control:** 
Manage the program state with commands like "stop atom" or "shutdown".
Information Retrieval: Get real-time data for time, date, and weather.
Media & Utilities: Play music via YouTube, solve math equations, and even read text from PDF files.
AI Search: Integrated AI lookup for general knowledge queries ("Who is...", "What is...").
**🤖 Robotics (Arduino Integration)**
ATOM communicates with Arduino hardware via serial signals to perform physical tasks:
Handshake: Sends signal 9 for a "shake hand" gesture.
Locomotion: Controls movement using signals 8 (forward), 7 (back), 6 (left), and 5 (right).
Peripherals: Toggle onboard LEDs with signals 0 (on) and 1 (off).
**🌍 Language & Translation**
Multilingual Support: Switch the primary interaction language (e.g., "speak Telugu").
Live Interpreter: Includes a dedicated "translator mode" for live conversation loops.
**🛠️ Command Reference**
Category,Command Examples,Action
System,"""exit"", ""shutdown""",Closes the program 
Media,"""play [song name]""",Plays audio from YouTube 
Arduino,"""forward"", ""back""",Sends movement signals to hardware 
Docs,"""read pdf [path]""",Extracts and reads PDF text 
AI,"""tell me about...""",Triggers AI/Search engine lookup.
**📂 Installation & SetupClone the Repository:**
Bash
git clone https://github.com/YOUR_USERNAME/ATOM.git
Upload Arduino Sketch:
Flash your Arduino with the provided .ino file to handle incoming serial signals (0-9).
Run the Assistant:Bashpython main.py 
