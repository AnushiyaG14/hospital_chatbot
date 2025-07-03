import streamlit as st
from dotenv import load_dotenv
from utils.redaction import redact_pii, unredact_pii
from utils.storage import store_appointment
import re
from openai import OpenAI
import os , json, time, spacy

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.groq.com/openai/v1"
)
nlp = spacy.load("en_core_web_sm")
MODEL = "llama3-8b-8192"
questions = [
    {"field": "name", "question": "What is your full name?"},
    {"field": "email", "question": "Thank you please provide your email address?"},
    {"field": "phone", "question": "Thank you enter your phone number?"},
    {"field": "address", "question": "Thank you enter your location?"},
    {"field": "symptoms", "question": "Please describe your symptoms."}
]

# --- Abuse Check using LLM ---
def check_abuse(message):
    try:
        prompt = f"Is the following message abusive or offensive? Respond with ONLY 'Yes' or 'No'. Message: \"{message}\""
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        reply = response.choices[0].message.content.strip().lower()
        return reply.startswith("yes")
    except Exception as e:
        st.warning(f"❌ Error in abuse check: {e}")
        return False



def generate_acknowledgment(field, value):
    prompt = f"The user just entered their {field}: {value}. Respond with a friendly short acknowledgment."
    print("📤 Acknowledgment Prompt to LLM:\n", prompt)
    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a polite assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"✅ Noted your {field}."

def validate_input(field, value):
    if field == "email":
        return re.match(r"[^@]+@[^@]+\.[^@]+", value)
    elif field == "phone":
        return re.match(r"^\+?\d{7,15}$", value)
    return True
def call_llm_acknowledgment(user_input_dict):
    user_prompt = "\n".join([f"{k.capitalize()}: {v}" for k, v in user_input_dict.items()])
    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a polite hospital assistant. Acknowledge user's input briefly, no confirmation yet."},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print("❌ Ack LLM Error:", e)
        return None



def call_llm_with_function(user_inputs):
    user_prompt = "\n".join([f"{k.capitalize()}: {v}" for k, v in user_inputs.items()])
    print("📤 Final Prompt to LLM:\n", user_prompt)
    print("📤 JSON sent to LLM:\n", json.dumps(user_inputs, indent=2))
    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "You are a hospital assistant. Confirm the appointment booking from user's details."},
                {"role": "user", "content": user_prompt}
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "store_appointment",
                        "description": "Store appointment info in DB",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                                "address": {"type": "string"},
                                "symptoms": {"type": "string"}
                            },
                            "required": ["name", "email", "phone", "address", "symptoms"]
                        }
                    }
                }
            ],
            tool_choice="auto"
        )

        choice = response.choices[0]

        # Check if function call was returned
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            func_call = choice.message.tool_calls[0]
            func_args = json.loads(func_call.function.arguments)
            confirmation_message = (
                f"✅ Appointment booked for {func_args['name']} at {func_args['address']}.\n"
                f"We've noted your symptoms: {func_args['symptoms']}.\n"
                f"A confirmation will be sent to {func_args['email']}."
            )
            return confirmation_message

        # If it's a regular text response
        elif choice.message.content:
            return choice.message.content

        return None

    except Exception as e:
        print("❌ LLM Error:", e)
        return None

# Session state setup
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "index" not in st.session_state:
    st.session_state.index = 0
if "completed" not in st.session_state:
    st.session_state.completed = False

st.title("🏥 Hospital Appointment Chatbot")
st.write("Welcome Book your appointment here")

# Show previous messages
for role, msg in st.session_state.chat_history:
    with st.chat_message(role):
        st.markdown(msg)

# Main conversation flow
if not st.session_state.completed:
    current_index = st.session_state.index

    if current_index < len(questions):
        current_q = questions[current_index]
        field = current_q["field"]
        question = current_q["question"]

        # Ask next question only if not already asked
        if not st.session_state.chat_history or st.session_state.chat_history[-1][0] != "assistant":
            st.session_state.chat_history.append(("assistant", question))
            st.rerun()
            st.stop()

        # Chat input
        user_input = st.chat_input("Your response")
        if user_input:
             # 🚨 Guardrail checks BEFORE anything else
            if check_abuse(user_input):
                st.warning("⚠️ Message blocked: abusive content detected.")
                st.stop()
           
            if not validate_input(field, user_input):
                st.warning(f"⚠️ Invalid {field}. Try again.")
            else:
                st.session_state.answers[field] = user_input
                st.session_state.chat_history.append(("user", user_input))

        # 🔐 Redact user input before LLM call
                redacted_input, mapping = redact_pii(st.session_state.answers)
                redacted_field_value = redacted_input[field]

                print("📤 Redacted Answers So Far:", json.dumps(redacted_input, indent=2))

        # 🧠 Send to LLM
                start = time.time()
                ack_response = generate_acknowledgment(field, redacted_field_value)
                latency = time.time() - start

        # ✅ Unredact LLM output before showing
                unredacted_ack = unredact_pii(ack_response, mapping)

        # 🧾 Debug logs
                print("📥 Redacted sent to LLM:", redacted_field_value)
                print("📤 Unmasked response from LLM:", unredacted_ack)

        # 🔁 Move to next question
                st.session_state.index += 1
                if st.session_state.index < len(questions):
                    next_q = questions[st.session_state.index]["question"]
                else:
                    next_q = "✅ All answers collected. Proceeding to book your appointment..."

        # ✅ Append unredacted response
                st.session_state.chat_history.append(
                    ("assistant", f"{unredacted_ack} ⏱️ {latency:.2f}s\n\n{next_q}")
                    )
                st.rerun()


    else:
        st.write("✅ All answers collected. Proceeding to book your appointment...")
        
        consent = st.checkbox("I consent to share my data for appointment booking.")
        if not consent:
            st.warning("We need your consent to proceed.")
            st.stop()
        # All inputs collected → redact & call LLM
        with st.spinner("🔒 Sending final redacted info to LLM..."):
            try:
                redacted_data, mapping = redact_pii(st.session_state.answers)

                start = time.time()
                final_response = call_llm_with_function(redacted_data)
                latency = time.time() - start

                if final_response:
                    unredacted = unredact_pii(final_response, mapping)
                    print("🔓 Unredacted response from LLM:", unredacted)

    # Only append once
                    if not any(unredacted in msg for role, msg in st.session_state.chat_history if role == "assistant"):
                        st.session_state.chat_history.append(
                            ("assistant", f"{unredacted} ⏱️ {latency:.2f}s")
                                )
                        store_appointment(st.session_state.answers, unredacted)

                    st.session_state.completed = True
                    st.rerun()                    
                else:
                    st.error("❌ No final response from LLM.")
            except Exception as e:
                st.error(f"❌ Error: {e}")
else:
    # Only show success message if it's not already in the chat history
    last_response = st.session_state.chat_history[-1][1] if st.session_state.chat_history else ""
    
    name = st.session_state.answers.get("name", "Your")
    final_line = f"✅ {name}, your appointment has already been submitted!"
    
    if final_line not in last_response:
        st.session_state.chat_history.append(("assistant", final_line))

    # Show the last assistant message
    with st.chat_message("assistant"):
        st.success(final_line)

    # ➕ Add reset button
    if st.button("🔁 Book another appointment"):
        st.session_state.chat_history = []
        st.session_state.answers = {}
        st.session_state.index = 0
        st.session_state.completed = False
        st.rerun()
