# Architecture
```
Streamlit UI (dashboard, forms, editable tables)
        |
Python service layer
  - Readiness scoring (rule-based)
  - Matching engine (rules + weighted fit score + explanations)
  - Scheduler (conflict detection + auto-resolve)
  - Notification generator
  - Offer tracker
        |
ML layer: scikit-learn LogisticRegression (placement probability / at-risk)
        |
Data layer: simulated pandas DataFrames (swap for PostgreSQL in production)
```

# Algorithms
- Readiness: weighted linear score with backlog penalty.
- Fit score: hybrid rule + weighted scoring (hard filters first, then score).
- At-risk model: StandardScaler + LogisticRegression on CGPA, backlogs, aptitude, mock, communication, projects, certs, skill count. At-risk = unplaced and P(placed) < 0.4.

# Evaluation
- Model hold-out accuracy (25% test split, stratified), shown in the app.
- Precision@K of shortlisted students vs historical placed flag, shown on the Matching page.

# Scalability / Multi-campus deployment
- Add campus_id to all tables; PostgreSQL backend.
- Containerise with Docker; deploy on cloud (e.g., AWS ECS / Streamlit Community Cloud for demo).
- Move ML to a FastAPI service; schedule retraining per campus.
- Future: embeddings/vector search for JD-resume matching, LLM explanations, chatbot, email/WhatsApp APIs.
