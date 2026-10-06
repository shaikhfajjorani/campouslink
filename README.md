# CampusLink v2 - AI-Powered Campus-to-Corporate Placement Management

## Run
```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Project structure
```
campuslink/
├── app.py               # Streamlit app (all modules)
├── requirements.txt
├── README.md
├── .streamlit/config.toml
└── docs/
    ├── workflow.md      # step-wise workflow
    └── architecture.md  # architecture, algorithms, evaluation, scalability
```

## Modules (sidebar pages)
Dashboard | Student Readiness | Matching | Scheduling | Notifications | Offer Tracking | At-Risk Students

Pipeline demonstrated: Profiling -> Matching -> Scheduling -> Notification -> Offer Tracking -> Analytics

## Note
All data is simulated with a fixed seed (reproducible). Replace `make_data()` / `make_offers()` with real or public datasets for production.

## v2 additions
- TF-IDF resume-vs-JD semantic similarity inside a hybrid (rules + NLP + readiness) fit score
- JD parser (skills, CGPA, branches) that creates new drives
- Scheduler with venue, shared-student and panel-capacity conflicts + auto-resolve
- Random Forest vs Logistic Regression, out-of-fold risk scores, per-student explanations, confusion matrix, feature importance
- Student 360 (radar, what-if simulator, AI summary stub), FAQ/eligibility chat assistant
- Multi-campus filter, funnel and skill/branch conversion charts, PPO & joining tracking
