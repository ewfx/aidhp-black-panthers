import streamlit as st
import faiss
import pandas as pd
import numpy as np
import json
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from dotenv import load_dotenv
import os
import streamlit.components.v1 as components

# Load API key and config
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

st.set_page_config(layout="wide")


# Cached resources
@st.cache_resource
def load_embedding_model():
    return SentenceTransformer("BAAI/bge-small-en")


@st.cache_resource
def load_faiss_indexes():
    try:
        cust_index = faiss.read_index("generated_embeddings/customer_faiss_index.index")
        prod_index = faiss.read_index("generated_embeddings/product_offer_faiss.index")
        return cust_index, prod_index
    except Exception as e:
        st.error(f"Error loading FAISS indexes: {e}")
        return None, None


@st.cache_data
def load_metadata():
    cust_meta = pd.read_csv("generated_embeddings/customer_vector_metadata.csv")
    prod_meta = pd.read_csv("generated_embeddings/product_offer_metadata.csv")
    return cust_meta, prod_meta


embedding_model = load_embedding_model()
customer_index, product_index = load_faiss_indexes()
customer_meta, product_meta = load_metadata()
gemini = genai.GenerativeModel("models/gemini-2.0-flash")


# Utility Functions
def embed_text(text):
    return embedding_model.encode(text, normalize_embeddings=True).reshape(1, -1)


def search_faiss(index, query_vec, k=3):
    D, I = index.search(query_vec, k)
    return I[0]


# Base Prompts (generic for all personas initially)
base_prompts = {
    "Personalized Product & Service Recommendations": [
        "Suggest banking products based on spending habits.",
        "Recommend an investment plan based on income and lifestyle.",
        "Find suitable insurance policies based on transaction data."
    ],
    "Customer Sentiment & Feedback Analysis": [
        "Analyze customer sentiment over time.",
        "Summarize top complaints and praises in feedback.",
        "Find customers at risk of leaving due to negative feedback."
    ],
    "Risk & Fraud Detection": [
        "Detect unusual transactions that may indicate fraud.",
        "Find customers with sudden high-value transactions.",
        "Identify potential fraud cases in recent credit card usage."
    ]
}


def get_suggested_prompts(persona):
    prompts = dict(base_prompts)

    if persona == "Customer":
        # Personalize recommendation prompts for customer
        prompts["Personalized Product & Service Recommendations"] = [
            "Suggest banking products based on my spending habits.",
            "Recommend an investment plan based on my income and lifestyle.",
            "Find suitable insurance policies based on my transaction data."
        ]
        # Remove sentiment category
        prompts.pop("Customer Sentiment & Feedback Analysis", None)
        # Update fraud prompt
        prompts["Risk & Fraud Detection"][1] = "Show if any sudden high-value transaction."

    elif persona == "Visitor":
        # Personalize recommendation prompts for visitor
        prompts["Personalized Product & Service Recommendations"] = [
            "Suggest banking products based on my spending habits.",
            "Recommend an investment plan based on my income and lifestyle.",
            "Find suitable insurance policies based on my transaction data."
        ]
        # Narrow down sentiment prompts for visitor
        prompts["Customer Sentiment & Feedback Analysis"] = [
            "Summarize top complaints and praises in feedback.",
            "Highlight few products which has received good feedback",
            "Highlight few products which has received frequent negative feedback",
        ]
        # Update fraud prompt
        prompts["Risk & Fraud Detection"][1] = "Show if any sudden high-value transaction."

    return prompts

    prompts = dict(base_prompts)
    if persona == "Customer":
        prompts.pop("Customer Sentiment & Feedback Analysis", None)
    if persona == "Visitor":
        prompts["Customer Sentiment & Feedback Analysis"] = [
            "Summarize top complaints and praises in feedback.",
            "Highlight common customer complaints for product improvement."
        ]
    return prompts


def generate_prompt(customer_json, products_text, persona, user_input):
    return f"""
You are a GenAI assistant for a bank.
Persona: {persona}

{user_input}

Customer Profile:
{customer_json}

Matching Products:
{products_text}
"""


def handle_query(customer_id, persona, user_input, visitor_details=None):
    if persona == "Banker/Admin":
        product_vec = embed_text(user_input)
        customer_idxs = search_faiss(customer_index, product_vec, k=3)
        customer_profiles = "\n\n".join(customer_meta.iloc[i].document for i in customer_idxs)
        return gemini.generate_content(
            f"Analyze the following customer profiles:\n{customer_profiles}\n{user_input}").text

    if persona == "Visitor":
        visitor_info = json.dumps(visitor_details, indent=2)
        return gemini.generate_content(f"Analyze the following visitor profile:\n{visitor_info}\n{user_input}").text

    record = customer_meta[customer_meta.customer_id == customer_id]
    if record.empty:
        return "❌ Customer not found."

    customer_json = record.iloc[0].document
    product_vec = embed_text(customer_json)
    product_idxs = search_faiss(product_index, product_vec, k=3)
    matched_products = "\n\n".join(product_meta.iloc[i].text for i in product_idxs)
    print("**********user_input :",user_input )
    prompt = generate_prompt(customer_json, matched_products, persona, user_input)
    return gemini.generate_content(prompt).text


# UI Setup
st.title("🤖 GenAI Banking Assistant")

if "persona" not in st.session_state:
    st.session_state.persona = None
if "selected_prompt" not in st.session_state:
    st.session_state.selected_prompt = ""

if st.session_state.persona is None:
    st.subheader("Select Your Persona")
    selected_persona = st.selectbox("Who are you?", ["Banker/Admin", "Customer", "Visitor"])
    if st.button("Continue"):
        st.session_state.persona = selected_persona
        st.rerun()
else:
    persona = st.session_state.persona
    st.sidebar.title("Session Control")
    st.sidebar.write(f"**Current Persona:** {persona}")
    if st.sidebar.button("🔁 Reset Persona"):
        st.session_state.persona = None
        st.rerun()

    suggested_prompts = get_suggested_prompts(persona)
    selected_category = st.selectbox("📂 Select a Category:", list(suggested_prompts.keys()))

    if persona == "Visitor" and selected_category == "Risk & Fraud Detection":
        st.markdown("## 🛡️ Smart Security. Seamless Banking.")
        st.markdown("""
Your security is our top priority. Our bank blends artificial intelligence and human expertise to safeguard your finances.

🔍 **Here’s how we protect you**:
- **Real-time fraud monitoring** across all transactions.
- **AI-powered pattern recognition** to detect unusual or suspicious activity.
- **Instant alerts** to notify you of high-risk events like sudden high-value transactions.
- **Multi-layer authentication** and secure transaction validation to block unauthorized access.
- **Proactive fraud prevention** for online, mobile, and card-based transactions.

✨ With us, your peace of mind comes standard.
        """)
        st.stop()


    st.markdown(f"### 📌 Suggested Prompts for {selected_category}")
    for prompt in suggested_prompts[selected_category]:
        if st.button(prompt):
            st.session_state.selected_prompt = prompt
            st.rerun()

    
    # 🎤 Mic button using browser Web Speech API
    st.markdown("🎙️ Speak your question or choose a prompt below:")
    components.html("""
    <script>
      const streamlitInput = window.parent.document.querySelectorAll('textarea')[0];
      function startDictation() {
        if (window.hasOwnProperty('webkitSpeechRecognition')) {
          var recognition = new webkitSpeechRecognition();
          recognition.continuous = false;
          recognition.interimResults = false;
          recognition.lang = "en-US";
          recognition.start();

          recognition.onresult = function(e) {
            const transcript = e.results[0][0].transcript;
            streamlitInput.value = transcript;
            streamlitInput.dispatchEvent(new Event('input', { bubbles: true }));
            recognition.stop();
          };

          recognition.onerror = function(e) {
            recognition.stop();
            alert("Speech recognition error: " + e.error);
          };
        } else {
          alert("Speech recognition not supported in this browser.");
        }
      }
    </script>
    <button onclick="startDictation()" style='padding: 0.5rem 1rem; margin-bottom: 1rem; border-radius: 10px; background-color: #4CAF50; color: white; border: none; font-size: 16px; cursor: pointer;'>
      🎤 Tap to Speak
    </button>
    """, height=110)


    user_input = st.text_area("✍️ Modify or enter your question:", value=st.session_state.selected_prompt)

    cust_id = None
    visitor_details = None

    if persona == "Customer":
        cust_id = st.text_input("Enter Your Customer ID:")
    elif persona == "Visitor":
        st.markdown("### Please enter your details for personalized insights")
        name = st.text_input("Name:")
        age = st.number_input("Age:", min_value=18, max_value=100, step=1)
        occupation = st.text_input("Occupation:")
        salary = st.number_input("Salary:", min_value=1000, step=500)
        interests = st.text_area("Interests (comma-separated):")
        visitor_details = {
            "Name": name,
            "Age": age,
            "Occupation": occupation,
            "Salary": salary,
            "Interests": interests.split(",") if interests else []
        }

    if st.button("🔎 Generate Insights"):
        with st.spinner("Processing..."):
            response = handle_query(cust_id, persona, user_input, visitor_details)
            st.markdown("## 📊 Insights:")
            st.markdown(response)

    st.session_state.selected_prompt = user_input
