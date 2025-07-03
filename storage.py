from pymongo import MongoClient
import os
import json
client = MongoClient(os.environ.get("MONGO_URI"))
db = client["clinic"]
collection = db["appointments"]

def store_appointment(raw, llm_summary, alert_flag=False, extra_fields=None):
    os.makedirs("data", exist_ok=True)
    data = {
        "raw_input": raw,
        "llm_summary": llm_summary,
        "alert_flag": alert_flag,
        "extra_fields": extra_fields or {}
    }

    # Save to file
    with open("data/appointments.json", "a") as f:
        json.dump(data, f)
        f.write("\n")

    # Save to MongoDB
    collection.insert_one(data)
