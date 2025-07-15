# HireCoach AI
#### Video Demo: https://youtu.be/V9GvmP-fZr8
#### Description:
HireCoach AI is a comprehensive web application designed to empower job seekers by providing intelligent, AI-powered tools for interview preparation and resume optimization. Built with Flask, SQLAlchemy, and leveraging the Google Gemini API, this platform offers a streamlined and interactive experience to help users enhance their hiring prospects. The application is secured with user authentication, ensuring a personalized and private experience for each user.

Core Features
1. User Authentication:
HireCoach AI provides a robust user authentication system, allowing users to register, log in, and securely manage their interactions with the platform. This ensures that personal practice data and resume optimization results are stored and accessible only by the respective user.

2. Interview Coach:
This feature acts as a virtual interview guide. Users input their desired job position, experience level, and industry. The AI then generates a series of common interview questions along with concise, ideal answers. This allows users to review potential questions and perfect their responses without the pressure of a live interview, providing a strong foundation for effective self-preparation.

3. Practice Interview:
The Practice Interview feature simulates a real interview experience. After providing job details, users are presented with interview questions one by one. They can then type in their answers. The application sends the user's response along with the ideal answer to the AI, which provides immediate, actionable feedback on the user's performance. This iterative feedback loop helps users identify weaknesses, refine their communication skills, and improve their answers in real-time. Upon completing a set number of questions, the AI generates an overall hiring percentage and general areas for improvement, offering a holistic view of their readiness.

4. Resume Optimizer:
The Resume Optimizer is a powerful tool that helps users tailor their resumes to specific job descriptions. Users upload or paste their resume text and the job description. The AI then performs a detailed analysis, providing:

A Match Score indicating how well the original resume aligns with the job requirements.

A Summary Message highlighting the strengths and weaknesses of the original resume.

Areas for Improvement for the original resume, presented as clear, actionable bullet points.

An Optimized Resume with suggested edits and improvements designed to increase its relevance and impact for the specified job.

An Analysis of Optimization Changes explaining the rationale behind each suggested modification.
All optimization results are stored securely in the user's account for future reference.

File Structure and Purpose
The HireCoach AI project is organized into a clear and manageable directory structure:

app.py: This is the main Flask application file. It contains:

Flask application setup and configuration.

Database models (User, ResumeOptimizationResult, PracticeSession) defined using SQLAlchemy for user management, storing resume optimization outputs, and persisting interview session data.

Google Gemini API configuration and interaction logic for generating questions, answers, feedback, and resume optimizations.

All application routes (/, /register, /login, /logout, /interview-coach, /interview-question-display, /get-question/<int:index>, /practice-interview, /practice-interview-question/<int:index>, /practice-evaluate, /practice-results, /resume-optimizer, /resume-optimizer-results).

Utility functions for parsing AI responses into structured data.

A login_required decorator to protect routes that require user authentication.

.env: This file stores environment variables, most critically your GEMINI_API_KEY and FLASK_SECRET_KEY. Using a .env file keeps sensitive information out of the main codebase, which is crucial for security and best practices in development.

templates/: This directory holds all the HTML files that serve as the user interface for the web application. Each file is responsible for rendering a specific part of the user experience:

error.html: Displays general error messages to the user.

index.html: The landing page of the application.

interview_coach.html: The form for users to input job details for the interview coach.

login.html: The user login form.

practice_interview.html: The interface for the interactive practice interview, where questions are displayed and user answers are collected.

practice_results.html: Displays the aggregated feedback and hiring percentage after a practice interview session.

practice_setup.html: The form for users to input job details to start a practice interview.

questions_display.html: Used by the Interview Coach feature to display AI-generated questions and ideal answers.

register.html: The user registration form.

resume_optimizer_results.html: Displays the detailed results of the resume optimization.

resume_optimizer_setup.html: The form for users to input their resume text and job description for optimization.

static/: This directory contains static assets for the web application:

styles.css: This stylesheet is used across all HTML pages to control the visual presentation, layout, and overall aesthetic of the application.

instance/: This folder contains the site.db file.

site.db: This is the SQLite database file where all application data is stored, including user accounts, practice interview sessions (both coach and practice modes), and resume optimization results. SQLAlchemy interacts with this file to manage the data.

Design Choices and Challenges
Developing HireCoach AI involved navigating several significant challenges and making deliberate design choices:

Session Management and Cookie Limits: A major hurdle was handling user session data, particularly for storing dynamically generated interview questions and practice data. Initially, storing this directly in Flask's session cookie led to the werkzeug.sansio.response: UserWarning: The 'session' cookie is too large error. This was a critical issue because large cookies can be silently ignored by browsers, leading to data loss and unexpected behavior.

Design Choice: To overcome this, the architecture was revised to persist all dynamic session-related data (like interview_questions and practice_data) into the SQLite database instead of the session cookie. This involved creating the PracticeSession model with a questions_data column (stored as a JSON string) and storing only a small session_id in the Flask session. This design ensures scalability, data persistence across requests, and adherence to cookie size limits. Generalizing the PracticeSession model to handle both 'coach' and 'practice' session types further streamlined the database schema.

AI API Integration and Selection: Integrating with a suitable Large Language Model (LLM) was central to the project's core functionality. The journey involved experimenting with multiple APIs before settling on Google Gemini.

Challenges:

API Response Robustness: Different APIs provided varied levels of structure in their responses, making consistent parsing challenging.

Token Limits and Cost: Balancing the detail of AI responses with token limits was crucial for performance and potential cost efficiency.

Context Management: Providing sufficient context to the AI (e.g., previous questions for uniqueness) while staying within prompt limits required careful crafting of prompts.

Reliability: Issues like DeadlineExceeded (timeouts) and GoogleAPIError required robust error handling and user feedback mechanisms.

Design Choice: The parse_ai_response, parse_feedback_response, parse_overall_results, and parse_resume_optimization_response utility functions were developed and refined iteratively to extract information reliably from raw AI text. The decision to use Google Gemini was based on its performance, cost-effectiveness, and the quality of its structured outputs for the specific tasks required (Q&A generation, feedback, and resume analysis). Error handling with try-except blocks for API calls was implemented to provide graceful degradation and informative messages to the user.

Application Design and Organization: Structuring a multi-feature web application with a clear separation of concerns (frontend, backend, database) was a continuous process.

Challenges: Deciding how to manage state (e.g., current interview progress), ensuring smooth transitions between different application features, and maintaining a consistent user experience.

Design Choice: Flask was chosen for its lightweight and flexible nature, allowing for rapid development. Jinja2 templating (templates/ folder) provided a clean way to separate HTML from Python logic. Static files (static/) ensured efficient serving of CSS. SQLAlchemy abstracted database interactions, making data management more straightforward. The introduction of login_required decorators simplified access control, centralizing authentication logic. As the project evolved, features like dynamic question loading via AJAX (get-question, practice-interview-question) were implemented to enhance responsiveness and avoid full page reloads, improving the user experience for interactive features.

These design choices and the solutions to the challenges were fundamental in building a stable, feature-rich, and user-friendly "HireCoach AI" application.

Made By Bojken Tocila.