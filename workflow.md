# Step-wise Workflow
1. Understand the pipeline: Profiling -> Matching -> Scheduling -> Notification -> Offer Tracking -> Analytics.
2. Create simulated data: 150 students, 3 drives, offers table.
3. Readiness score (0-100): CGPA 25%, aptitude 25%, mock 25%, communication 15%, projects 5%, certifications 5%, minus 4 per backlog. Levels: Not Ready <45, Developing <60, Ready <75, Highly Employable >=75.
4. Skill-gap analysis: required skills minus student skills, with preparation tips.
5. Matching: hard eligibility (CGPA, branch, backlogs) + fit score = 45% skill coverage + 30% readiness + 25% mock vs benchmark. Shortlist if fit >= 60.
6. Explainable output: reason text per student.
7. Conflict-aware scheduling: same date/slot, venue double-booking, students shortlisted in both; auto-resolve moves clashing drive to next free slot.
8. Notifications: shortlist messages and document reminders (simulated send).
9. Offer and documentation tracking: editable table (CTC, offer status, docs status).
10. Analytics: branch-wise conversion, CTC trends, at-risk prediction (logistic regression), mentor escalation.
11. Evaluation: hold-out accuracy and Precision@K vs simulated history.
