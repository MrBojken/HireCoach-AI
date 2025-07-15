import os # Provides a way to interact with the operating system, used for environment variables and file paths
from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify # Core Flask components for web application development
from dotenv import load_dotenv # Loads environment variables from a .env file
import logging # Provides facilities for logging events and debugging
import re # Provides regular expression operations, used for parsing text
import google.generativeai as genai # Imports the Google Generative AI client library for interacting with Gemini models
from google.api_core.exceptions import DeadlineExceeded, GoogleAPIError # Handles specific exceptions from Google API calls, like timeouts or general errors
import json # Used for serializing and deserializing JSON data, especially for database storage

# Imports for user authentication and database management
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Configure the logging system for application monitoring and debugging
# Logs informational messages, warnings, and errors with timestamps
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from the .env file
# This secures sensitive data like API keys by keeping them out of the source code
load_dotenv()

# Initialize the Flask web application instance
app = Flask(__name__)

# Configure the application's secret key for session security
# It's fetched from environment variables for production, with a fallback for development
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'a_very_secret_key_that_should_be_in_env_in_prod')

# Configure SQLAlchemy to connect to a SQLite database named 'site.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
# Disable SQLAlchemy's event system tracking for better performance if not explicitly needed
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Initialize the SQLAlchemy database object, associating it with the Flask app
db = SQLAlchemy(app)

# Define the User database model
# Represents the 'user' table and its columns
class User(db.Model):
    # Unique identifier for each user, serves as the primary key
    id = db.Column(db.Integer, primary_key=True)
    # User's unique username, required and must be unique across all users
    username = db.Column(db.String(80), unique=True, nullable=False)
    # Stores the securely hashed password for authentication
    password_hash = db.Column(db.String(128), nullable=False)

    # Method to hash a plaintext password before saving to the database
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Method to verify a given plaintext password against the stored hash
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # String representation of a User object for debugging
    def __repr__(self):
        return f'<User {self.username}>'

# Define the ResumeOptimizationResult database model
# Stores the results of resume analysis and optimization for each user
class ResumeOptimizationResult(db.Model):
    # Unique ID for each resume optimization record
    id = db.Column(db.Integer, primary_key=True)
    # Foreign key linking this result to a specific user
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Stores the match score as a string (e.g., "75%")
    match_score = db.Column(db.String(10))
    # AI-generated summary message for the original resume
    summary_message = db.Column(db.Text)
    # List of suggested improvements for the original resume, stored as a text block
    original_improvements = db.Column(db.Text)
    # The full text of the AI-optimized resume
    optimized_resume_text = db.Column(db.Text)
    # Explanation of the changes made during optimization
    changes_analysis = db.Column(db.Text)
    # Timestamp indicating when the optimization was performed
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    # String representation of a ResumeOptimizationResult object for debugging
    def __repr__(self):
        return f'<ResumeResult {self.id} for user {self.user_id}>'

# Define the PracticeSession database model
# Used to store data for both Interview Coach (question display) and Practice Interview (interactive) sessions
class PracticeSession(db.Model):
    # Unique ID for each practice session
    id = db.Column(db.Integer, primary_key=True)
    # Foreign key linking this session to a specific user
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # The job position relevant to this practice session
    job_position = db.Column(db.String(255))
    # The experience level chosen for the session
    experience_level = db.Column(db.String(100))
    # The industry associated with the practice session
    industry = db.Column(db.String(100))
    
    # Type of session: 'coach' for displaying questions, 'practice' for interactive interview
    session_type = db.Column(db.String(50), nullable=False, default='practice') 
    
    # Stores all questions, answers, user responses, and AI feedback as a JSON string
    # This allows flexible storage of complex, dynamic session data that varies by session_type
    questions_data = db.Column(db.Text, default="[]") 
    
    # Timestamp indicating when the practice session was created
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())

    # String representation of a PracticeSession object for debugging
    def __repr__(self):
        return f'<PracticeSession {self.id} ({self.session_type}) for user {self.user_id}>'

# Ensure the database tables are created within the Flask application context
# This command creates the 'user', 'resume_optimization_result', and 'practice_session' tables if they don't already exist
with app.app_context():
    db.create_all()
    logging.info("Database and User/ResumeOptimizationResult/PracticeSession tables ensured to be created.")

# Configure the Google Generative AI model
try:
    # Retrieve the Gemini API key securely from environment variables
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    # Raise an error if the API key is not found
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY not found in .env file.")
    # Initialize the Generative AI client with the API key
    genai.configure(api_key=gemini_api_key)
    # Load the specific Gemini model for content generation
    model = genai.GenerativeModel('gemini-1.5-flash-latest')
    logging.info("Gemini model 'gemini-1.5-flash-latest' initialized successfully.")
# Handle any exceptions during API key retrieval or model initialization
except Exception as e:
    logging.error(f"Error initializing Google Gemini client: {e}")
    logging.error("Please ensure GEMINI_API_KEY is set correctly in your .env file.")
    # Set model to None to prevent subsequent AI calls from crashing the application
    model = None

# --- Application Constants ---
# Maximum number of questions generated for the Interview Coach feature
MAX_INITIAL_QUESTIONS = 5 
# Maximum number of questions to be used in a Practice Interview session
MAX_PRACTICE_QUESTIONS = 5 

# --- Utility Functions for AI Response Parsing ---

# Parses the AI's raw text response for interview questions and ideal answers
# Uses regular expressions to extract structured 'question' and 'answer' pairs
def parse_ai_response(response_text):
    qa_pairs = []
    # Regex to find "Question: [text] Answer: [text]" blocks in the AI's response
    # It accounts for various delimiters between Q&A pairs
    matches = re.findall(r"Question:\s*(.*?)\s*Answer:\s*(.*?)(?=(Question:|$))", response_text, re.DOTALL)

    # Iterate through the regex matches to extract and clean question and answer text
    for q_match, a_match, _ in matches:
        question = q_match.strip()
        answer = a_match.strip()
        # Only add valid, non-empty questions and answers
        if question and answer:
            qa_pairs.append({'question': question, 'answer': answer})
        else:
            logging.warning(f"Skipping malformed Q&A pair: Question='{question[:50]}...', Answer='{answer[:50]}...'")
    return qa_pairs

# Parses the AI's raw text response specifically for individual feedback
# Returns the cleaned feedback text
def parse_feedback_response(response_text):
    return response_text.strip()

# Parses the AI's raw text response for overall practice interview results
# Extracts hiring percentage, areas for improvement, and a general message
def parse_overall_results(response_text):
    results = {
        'hiring_percentage': 'N/A',
        'areas_for_improvement': 'N/A',
        'overall_message': response_text.strip() # Default to raw text if specific parsing fails
    }

    # Regex to find the hiring percentage (e.g., "Hiring Percentage: 75%")
    percent_match = re.search(r"Hiring Percentage:\s*(\d{1,3})%", response_text, re.IGNORECASE)
    if percent_match:
        results['hiring_percentage'] = f"{percent_match.group(1)}%"

    # Regex to find the "Areas for Improvement" section
    improvement_match = re.search(r"Areas for Improvement:\s*(.*?)(?=(Overall Message:|Overall Feedback:|$))", response_text, re.IGNORECASE | re.DOTALL)
    if improvement_match:
        results['areas_for_improvement'] = improvement_match.group(1).strip()
    
    # Regex to find the "Overall Message" or "Overall Feedback" section
    overall_message_match = re.search(r"(?:Overall Message|Overall Feedback):\s*(.*)", response_text, re.IGNORECASE | re.DOTALL)
    if overall_message_match:
        results['overall_message'] = overall_message_match.group(1).strip()
    
    return results

# Parses the AI's raw text response for resume optimization details
# Extracts match score, summary, improvements, optimized resume text, and changes analysis
def parse_resume_optimization_response(response_text):
    results = {
        'match_score': 'N/A',
        'summary_message': 'N/A',
        'original_improvements': [],
        'optimized_resume_text': 'Could not generate optimized resume.',
        'changes_analysis': 'Could not generate analysis of changes.'
    }

    # Helper function to remove markdown bolding from extracted text
    def clean_asterisks(text):
        return re.sub(r'\*\*(.*?)\*\*', r'\1', text).strip()

    # Regex to extract the match score, accounting for markdown bolding
    score_match = re.search(r"\*\*Match Score:\*\*\s*(\d{1,3}%)", response_text, re.IGNORECASE)
    if score_match:
        results['match_score'] = score_match.group(1).strip()
    else:
        # Fallback regex if percentage sign or bolding is missing
        score_match_fallback = re.search(r"Match Score:\s*(\d{1,3})", response_text, re.IGNORECASE)
        if score_match_fallback:
            results['match_score'] = f"{score_match_fallback.group(1).strip()}%"

    # Regex to extract the summary message
    summary_match = re.search(r"\*\*Summary Message:\*\*\s*(.*?)(?=\*\*Original Resume Analysis - Areas for Improvement:\*\*|\*\*Optimized Resume:\*\*|$)", response_text, re.IGNORECASE | re.DOTALL)
    if summary_match:
        results['summary_message'] = clean_asterisks(summary_match.group(1).strip())

    # Regex to extract "Areas for Improvement" section
    improvements_match = re.search(r"\*\*Original Resume Analysis - Areas for Improvement:\*\*\s*(.*?)(?=\*\*Optimized Resume:\*\*|$)", response_text, re.IGNORECASE | re.DOTALL)
    if improvements_match:
        raw_areas = improvements_match.group(1).strip().split('\n')
        # Clean markdown from each bullet point and filter out empty lines
        results['original_improvements'] = [clean_asterisks(re.sub(r"^[-\*]\s*", "", line).strip()) for line in raw_areas if line.strip()]

    # Regex to extract the "Optimized Resume" text
    optimized_resume_match = re.search(r"\*\*Optimized Resume:\*\*\s*(.*?)(?=\*\*Analysis of Optimization Changes:\*\*|$)", response_text, re.IGNORECASE | re.DOTALL)
    if optimized_resume_match:
        # No asterisk cleaning here as the resume text itself might use bolding
        results['optimized_resume_text'] = optimized_resume_match.group(1).strip()

    # Regex to extract the "Analysis of Optimization Changes" section
    changes_analysis_match = re.search(r"\*\*Analysis of Optimization Changes:\*\*\s*(.*)", response_text, re.IGNORECASE | re.DOTALL)
    if changes_analysis_match:
        results['changes_analysis'] = clean_asterisks(changes_analysis_match.group(1).strip())
    
    # Log a warning if any crucial parts of the parsing failed
    if not all([results['match_score'] != 'N/A', results['summary_message'] != 'N/A', results['optimized_resume_text'] != 'Could not generate optimized resume.', results['changes_analysis'] != 'Could not generate analysis of changes.']):
        logging.warning("Resume optimization parsing incomplete. Full AI response:\n%s", response_text)

    return results

# Generates overall feedback and hiring percentage for a complete practice interview session
def generate_overall_practice_feedback(practice_data, job_details):
    # Return immediately if the AI model is not initialized
    if not model:
        return {'hiring_percentage': 'N/A', 'areas_for_improvement': 'AI service not available.', 'overall_message': 'AI service not available.'}

    # Return specific message if no practice data is provided
    if not practice_data:
        return {'hiring_percentage': 'N/A', 'areas_for_improvement': 'No practice data to evaluate.', 'overall_message': 'No practice data to evaluate.'}

    # Construct the detailed prompt for the AI to provide overall assessment
    feedback_summary_prompt = "Review the following interview questions, ideal answers, user's answers, and individual AI feedback.\n"
    feedback_summary_prompt += "Based on this, provide an overall hiring percentage (e.g., '75%').\n"
    feedback_summary_prompt += "Then, list 3-5 key areas for improvement across all answers. Be specific and actionable.\n"
    feedback_summary_prompt += "Finally, provide an encouraging overall message to the user, no more than 3 sentences.\n"
    feedback_summary_prompt += "Use the following strict format:\n\n"
    feedback_summary_prompt += "Hiring Percentage: [X%]\n"
    feedback_summary_prompt += "Areas for Improvement:\n"
    feedback_summary_prompt += "- [Area 1]\n"
    feedback_summary_prompt += "- [Area 2]\n"
    feedback_summary_prompt += "- [Area 3]\n"
    feedback_summary_prompt += "Overall Message: [Your encouraging message]\n\n"

    # Append each question's details, user's answer, and individual feedback to the prompt
    for i, data in enumerate(practice_data):
        feedback_summary_prompt += f"--- Question {i+1} ---\n"
        feedback_summary_prompt += f"Question: {data['question']}\n"
        feedback_summary_prompt += f"Ideal Answer: {data['answer']}\n" # 'answer' field holds the ideal answer
        feedback_summary_prompt += f"Your Answer: {data['user_answer']}\n"
        feedback_summary_prompt += f"Individual Feedback: {data['ai_feedback']}\n\n"

    # Add context about the job position if available
    context_phrase = ""
    if job_details and job_details.get("position"):
        context_phrase = f" for a {job_details['experience']} {job_details['position']} position{f' in the {job_details['industry']} industry' if job_details['industry'] else ''}"
    feedback_summary_prompt += f"Considering the candidate's responses for the {context_phrase}."

    try:
        # Send the comprehensive prompt to the Gemini model
        response = model.generate_content(
            feedback_summary_prompt,
            # Set generation configuration for desired output length and creativity
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=500, # Limit output to prevent excessively long responses
                temperature=0.7, # Controls creativity, lower for more focused answers
            ),
            # Set a longer timeout for this more complex overall evaluation
            request_options={'timeout': 120}
        )
        raw_text = response.text.strip()
        logging.info("Gemini API call completed for overall practice feedback.")
        logging.debug(f"Raw text from Gemini (overall feedback):\n{raw_text[:500]}...")
        # Parse the AI's response to extract structured overall results
        return parse_overall_results(raw_text)

    # Handle specific API errors during generation
    except DeadlineExceeded as e:
        logging.error(f"Gemini API Timeout for overall feedback: {e}")
        return {'hiring_percentage': 'N/A', 'areas_for_improvement': f"AI generation timed out for overall feedback: {e}", 'overall_message': 'Please try again.'}
    except GoogleAPIError as e:
        logging.error(f"Google Gemini API Error for overall feedback: {e}")
        return {'hiring_percentage': 'N/A', 'areas_for_improvement': f"AI service error for overall feedback: {e}", 'overall_message': 'Please try again.'}
    # Catch any other unexpected errors
    except Exception as e:
        logging.critical(f"An unexpected error occurred during overall feedback generation: {e}", exc_info=True)
        return {'hiring_percentage': 'N/A', 'areas_for_improvement': f"An unexpected server error occurred: {e}", 'overall_message': 'Please try again.'}

# --- Flask Routes ---

# Decorator to ensure a user is logged in to access a route
# If not logged in, it redirects them to the login page
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if 'user_id' exists in the current session
        if 'user_id' not in session:
            # Flash a warning message and redirect to login, passing the original URL for redirection after login
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login', next=request.url))
        # If logged in, execute the original function
        return f(*args, **kwargs)
    return decorated_function

# Route for the main homepage
@app.route("/")
def index():
    # Renders the 'index.html' template for the home page view
    return render_template("index.html")

# --- User Authentication Routes ---

# Route for user registration (GET and POST methods)
@app.route("/register", methods=["GET", "POST"])
def register():
    # If a user is already logged in, redirect them to the homepage
    if 'user_id' in session: 
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    # Handle POST requests when the registration form is submitted
    if request.method == "POST":
        # Retrieve form data and strip leading/trailing whitespace
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()
        confirm_password = request.form.get("confirm_password").strip()

        # Validate that all required fields are provided
        if not username or not password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("register.html", username=username)

        # Validate that the password and confirmation match
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html", username=username)

        # Validate password length for basic security
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html", username=username)

        # Check if the chosen username already exists in the database
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists. Please choose a different one.", "error")
            return render_template("register.html", username=username)

        # Create a new User object with the provided username
        new_user = User(username=username)
        # Hash the password and set it for the new user object
        new_user.set_password(password)
        # Add the new user to the database session
        db.session.add(new_user)
        # Commit the transaction to save the new user to the database
        db.session.commit()
        # Flash a success message and redirect the user to the login page
        flash("Account created successfully! Please log in.", "success")
        return redirect(url_for('login'))
    # Handle GET requests: simply render the registration form
    return render_template("register.html")

# Route for user login (GET and POST methods)
@app.route("/login", methods=["GET", "POST"])
def login():
    # If a user is already logged in, redirect them to the homepage
    if 'user_id' in session: 
        flash("You are already logged in.", "info")
        return redirect(url_for('index'))

    # Handle POST requests when the login form is submitted
    if request.method == "POST":
        # Retrieve username and password from the form
        username = request.form.get("username").strip()
        password = request.form.get("password").strip()

        # Query the database to find the user by username
        user = User.query.filter_by(username=username).first()

        # Check if the user exists and if the provided password is correct
        if user and user.check_password(password):
            # Store the user's ID and username in the Flask session upon successful login
            session['user_id'] = user.id
            session['username'] = user.username 
            flash(f"Welcome back, {user.username}!", "success")
            # Redirect to the 'next' page if specified, otherwise to the homepage
            next_page = request.args.get('next') or url_for('index')
            return redirect(next_page)
        else:
            # Flash an error message for invalid credentials
            flash("Invalid username or password.", "error")
    # Handle GET requests: simply render the login form
    return render_template("login.html")

# Route for user logout
@app.route("/logout")
def logout():
    # Remove 'user_id' from the session to log out the user
    session.pop('user_id', None)
    # Remove 'username' from the session
    session.pop('username', None) 
    # Clear any active interview coach or practice session IDs upon logout
    session.pop('current_coach_session_id', None)
    session.pop('current_practice_session_id', None)
    # Clear temporary job details from session
    session.pop('job_details', None) 
    # Ensure session changes are saved immediately
    session.modified = True
    # Flash an informational message confirming logout
    flash("You have been logged out.", "info")
    # Redirect to the homepage after logout
    return redirect(url_for('index'))

# PROTECTED ROUTES (Require Login)

# Route for the Interview Coach feature, accessible only to logged-in users
@app.route("/interview-coach", methods=["GET", "POST"])
@login_required # Ensures that only authenticated users can access this route
def interview_coach():
    # Handle GET requests, which typically display the initial form for setting up the coach session
    if request.method == "GET":
        return render_template("interview_coach.html")
    # Handle POST requests, which occur when the user submits the interview coach setup form
    else: 
        logging.info("POST request received for /interview-coach.")
        # Retrieve the current user's ID from the session
        user_id = session.get('user_id')

        # Extract job details from the submitted form data
        job_position = request.form.get("job_position")
        experience_level = request.form.get("experience")
        industry = request.form.get("industry")

        # Validate that the job position field is not empty
        if not job_position:
            logging.warning("Job position empty, redirecting to error page.")
            flash("Job position cannot be empty. Please go back and provide one.", "error")
            return render_template("error.html", message="Job position cannot be empty. Please go back and provide one.", go_back_url=url_for('interview_coach'))

        # Check if the Gemini AI model has been successfully initialized
        if model is None:
            logging.error("Gemini model not initialized, returning error page.")
            flash("Google Gemini AI client not initialized. Check API key in .env and restart server.", "error")
            return render_template("error.html", message="Google Gemini AI client not initialized. Check API key in .env and restart server.", go_back_url=url_for('interview_coach'))

        # Create a new PracticeSession record in the database for this 'coach' mode session
        new_coach_session = PracticeSession(
            user_id=user_id,
            job_position=job_position,
            experience_level=experience_level,
            industry=industry,
            session_type='coach', # Explicitly set the session type to 'coach'
            questions_data="[]" # Initialize the questions data as an empty JSON array string
        )
        # Add the new session object to the database session
        db.session.add(new_coach_session)
        # Commit the transaction to save the new session to the database
        db.session.commit()
        
        # Store the ID of the newly created session in the Flask session
        session["current_coach_session_id"] = new_coach_session.id
        
        # Store job details in the Flask session for easy access, though the main source is now the DB
        session["job_details"] = { 
            "position": job_position,
            "experience": experience_level,
            "industry": industry
        }
        
        # Mark the session as modified to ensure changes are saved
        session.modified = True
        logging.info(f"Coach session initiated with DB ID: {new_coach_session.id}. Questions will be generated on demand.")

        # Attempt to generate the very first interview question for display
        logging.info("Calling Gemini API for initial content generation (first question for coach)...")
        try:
            # Construct the prompt for the Gemini model, requesting one question and answer
            prompt = f"""
            Generate 1 distinct interview question and its concise, ideal answer for a {experience_level} {job_position} position{f' in the {industry} industry' if industry else ''}.
            The answer should be no more than 3-5 sentences.
            Ensure the question and answer pair follows this strict format:
            Question: [Your question here]
            Answer: [Your ideal answer here]
            """
            # Call the Gemini API to generate content
            response = model.generate_content(
                prompt,
                # Configure generation parameters: max output tokens and creativity temperature
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=500,
                    temperature=0.7,
                ),
                request_options={'timeout': 90} # Set a timeout for the API request
            )
            raw_text = response.text.strip()
            logging.info("Gemini API call completed for first coach question.")
            logging.debug(f"Raw text from Gemini (first coach question):\n{raw_text[:500]}...")

            # Parse the AI's response to extract the question and answer
            parsed_qa = parse_ai_response(raw_text)

            # If a valid question and answer pair was successfully parsed
            if parsed_qa:
                # Load existing questions data from the database session
                coach_questions_list = json.loads(new_coach_session.questions_data)
                # Append the newly generated question and answer
                coach_questions_list.append(parsed_qa[0])
                # Update the questions data in the database session object
                new_coach_session.questions_data = json.dumps(coach_questions_list)
                # Commit changes to the database
                db.session.commit()

                logging.info("First Q&A pair stored in DB for coach session. Redirecting to display page.")
                # Redirect to the page where questions are displayed
                return redirect(url_for("interview_question_display"))
            else:
                logging.warning("No valid Q&A pair parsed from AI response for first coach question.")
                flash("AI did not generate a valid first question. Try a different prompt/position.", "error")
                return render_template("error.html", message="AI did not generate a valid first question. Try a different prompt/position.", go_back_url=url_for('interview_coach'))

        # Handle specific API timeout error
        except DeadlineExceeded as e:
            logging.error(f"Gemini API Timeout for initial coach question: {e}")
            flash(f"AI generation timed out for the first question. Please try again. Details: {e}", "error")
            return render_template("error.html", message="AI generation timed out for the first question. Please try again.", go_back_url=url_for('interview_coach'))
        # Handle general Google API errors
        except GoogleAPIError as e:
            logging.error(f"Google Gemini API Error for initial coach question: {e}")
            flash(f"Failed to generate initial question from AI due to an API error: {e}. Check API key or Google Cloud console for issues.", "error")
            return render_template("error.html", message=f"AI Service Error for initial question: {e}", go_back_url=url_for('interview_coach'))
        # Catch any other unexpected errors during the process
        except Exception as e:
            logging.critical(f"An unexpected error occurred during initial coach question generation or parsing: {e}", exc_info=True)
            flash("An unexpected server error occurred during initial question generation. Please try again.", "error")
            return render_template("error.html", message="An unexpected server error occurred. Please try again. Check terminal for details.", go_back_url=url_for('interview_coach'))


# Route to display the interview questions for the coach mode
@app.route("/interview-question-display")
@login_required # Requires user to be logged in
def interview_question_display():
    # Retrieve the active coach session ID from the Flask session
    coach_session_id = session.get("current_coach_session_id")
    # If no active session ID is found, redirect to the interview coach setup page
    if not coach_session_id:
        flash("No active interview coach session found. Please start a new session.", "info")
        return redirect(url_for("interview_coach"))

    # Fetch the corresponding PracticeSession object from the database using the session ID
    current_coach_session = PracticeSession.query.get(coach_session_id)
    # If the session is not found in the database, redirect to setup
    if not current_coach_session:
        flash("Interview coach session not found in database. Please start a new session.", "error")
        return redirect(url_for("interview_coach"))

    logging.info("Rendering questions_display.html for coach session.")
    # Render the template to display questions, passing the job position from the database session
    return render_template(
        "questions_display.html",
        job_position=current_coach_session.job_position 
    )

# AJAX endpoint to fetch interview questions for the coach display
@app.route("/get-question/<int:index>", methods=["GET"])
@login_required # Requires user to be logged in
def get_question(index):
    """
    AJAX endpoint to fetch a specific question by index for Interview Coach display.
    Generates a new question if the index is beyond current stored questions.
    """
    # Fetch the current coach session ID from the Flask session
    coach_session_id = session.get("current_coach_session_id")
    # Return an error if no active coach session is found
    if not coach_session_id:
        logging.error("No active coach session found during /get-question request.")
        return jsonify({"error": "No active interview coach session found. Please start a new one."}), 400
    
    # Retrieve the PracticeSession object from the database
    current_coach_session = PracticeSession.query.get(coach_session_id)
    # Validate that the session exists and is of type 'coach'
    if not current_coach_session or current_coach_session.session_type != 'coach':
        logging.error(f"Coach session {coach_session_id} not found or type mismatch.")
        return jsonify({"error": "Interview coach session not found or invalid. Please start a new one."}), 400

    # Load the list of questions from the database session object (stored as JSON string)
    questions = json.loads(current_coach_session.questions_data)
    
    # Extract job details from the database session object for AI prompting
    job_details = {
        "position": current_coach_session.job_position,
        "experience": current_coach_session.experience_level,
        "industry": current_coach_session.industry
    }
    
    # Return an error if the AI model is not available
    if model is None:
        return jsonify({"error": "AI service not available."}), 500

    # If the requested index is within the bounds of already generated questions
    if 0 <= index < len(questions):
        logging.info(f"Returning existing coach question at index {index}.")
        # Return the existing question and its ideal answer as JSON
        return jsonify({
            "question": questions[index]["question"],
            "answer": questions[index]["answer"], # This is the ideal answer for display in coach mode
            "index": index,
            "total": MAX_INITIAL_QUESTIONS # Report the predefined maximum number of questions
        })
    # If the requested index is the next in sequence, meaning a new question needs to be generated
    elif index == len(questions): 
        # Check if the maximum number of questions for coach mode has been reached
        if len(questions) >= MAX_INITIAL_QUESTIONS:
            logging.info(f"Attempted to generate coach question {index}, but max limit ({MAX_INITIAL_QUESTIONS}) reached.")
            return jsonify({"error": "Maximum questions reached."}), 400

        logging.info(f"Generating new coach question for index {index}...")
        try:
            previous_questions_text = ""
            # If there are existing questions, include them in the prompt for context and uniqueness
            if questions:
                # Get a subset of previous questions to ensure the new one is unique
                previous_q_for_prompt = [q['question'] for q in questions[-MAX_INITIAL_QUESTIONS:]] 
                previous_questions_text = "Here are questions that have already been asked (ensure your new question is unique):\n" + "\n".join([f"- {q}" for q in previous_q_for_prompt]) + "\n\n"

            # Construct the prompt for the AI to generate a new, unique question and answer
            prompt = f"""
            {previous_questions_text}
            Generate 1 distinct, new interview question and its concise, ideal answer for a {job_details['experience']} {job_details['position']} position{f' in the {job_details['industry']} industry' if job_details['industry'] else ''}. This new question MUST be UNIQUE and DIFFERENT from any of the previously listed questions.
            The answer should be no more than 3-5 sentences.
            Ensure the question and answer pair follows this strict format:
            Question: [Your unique question here]
            Answer: [Your ideal answer here]
            """
            
            # Call the Gemini API to generate the new question
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=500,
                    temperature=0.7,
                ),
                request_options={'timeout': 90}
            )
            raw_text = response.text.strip()
            logging.info(f"Gemini API call completed for coach question {index}.")
            logging.debug(f"Raw text from Gemini (coach question {index}):\n{raw_text[:500]}...")

            # Parse the AI's response
            parsed_qa = parse_ai_response(raw_text)

            # If a valid new question is parsed
            if parsed_qa:
                new_qa = parsed_qa[0]
                # Append the new question to the list and update the database
                questions.append(new_qa)
                current_coach_session.questions_data = json.dumps(questions)
                db.session.commit()
                logging.info(f"New Q&A pair generated and stored for coach index {index} in DB.")
                
                # Return the new question data as JSON
                return jsonify({
                    "question": new_qa["question"],
                    "answer": new_qa["answer"],
                    "index": index,
                    "total": MAX_INITIAL_QUESTIONS
                })
            else:
                logging.warning(f"No valid Q&A pair parsed from AI response for new coach question at index {index}. Raw: {raw_text[:200]}")
                return jsonify({"error": "Failed to generate a new question. AI response was malformed."}), 500

        # Handle API timeout specifically for question generation
        except DeadlineExceeded as e:
            logging.error(f"Gemini API Timeout for coach question {index}: {e}")
            return jsonify({"error": "AI generation timed out for this question. Please try again."}), 504
        # Handle general Google API errors during generation
        except GoogleAPIError as e:
            logging.error(f"Google Gemini API Error for coach question {index}: {e}")
            return jsonify({"error": f"AI Service Error for this question: {e}"}), 500
        # Catch any other unexpected errors
        except Exception as e:
            logging.critical(f"An unexpected error occurred generating coach question {index}: {e}", exc_info=True)
            return jsonify({"error": "An unexpected server error occurred while fetching this question."}), 500
    # If an invalid index is requested (e.g., negative or too far ahead)
    else:
        logging.warning(f"Invalid coach question index requested: {index}. Max allowed: {MAX_INITIAL_QUESTIONS}.")
        return jsonify({"error": "Invalid question index requested."}), 404

# Route for the Practice Interview feature, handling both setup display and submission
@app.route("/practice-interview", methods=["GET", "POST"])
@login_required # Requires user to be logged in
def practice_interview():
    # Check if the AI model is available before proceeding
    if model is None:
        flash("AI service not available. Cannot start practice interview.", "error")
        return render_template("error.html", message="AI service not available.", go_back_url=url_for('index'))

    # Handle GET requests: display the initial setup form for the practice interview
    if request.method == "GET":
        logging.info("GET request received for /practice-interview. Rendering practice_setup.html.")
        return render_template("practice_setup.html")
    
    # Handle POST requests: process the form submission from the practice setup
    else: 
        logging.info("POST request received for /practice-interview (from practice_setup.html).")
        # Retrieve the user ID from the session
        user_id = session.get('user_id')

        # Extract job details from the submitted form
        job_position = request.form.get("job_position")
        experience_level = request.form.get("experience")
        industry = request.form.get("industry")

        # Validate that the job position field is not empty
        if not job_position:
            flash("Job position cannot be empty for practice. Please provide one.", "error")
            return render_template("error.html", message="Job position cannot be empty for practice. Please go back and provide one.", go_back_url=url_for('practice_interview'))

        # Create a new PracticeSession record in the database for this 'practice' mode session
        new_practice_session = PracticeSession(
            user_id=user_id,
            job_position=job_position,
            experience_level=experience_level,
            industry=industry,
            session_type='practice', # Explicitly set the session type to 'practice'
            questions_data="[]" # Initialize with an empty JSON array string for questions
        )
        # Add the new session to the database session
        db.session.add(new_practice_session)
        # Commit the transaction to save the new session
        db.session.commit()
        
        # Store the ID of the new practice session in the Flask session
        session["current_practice_session_id"] = new_practice_session.id
        
        # Store job details in the Flask session for convenience during the practice session
        session["job_details"] = { 
            "position": job_position,
            "experience": experience_level,
            "industry": industry
        }
        
        # Mark the session as modified
        session.modified = True

        logging.info(f"Practice session initiated with DB ID: {new_practice_session.id}. Questions will be generated on demand.")
        # Redirect to the actual practice interview interface
        return render_template(
            "practice_interview.html",
            job_position=job_position # Pass the job position directly to the template
        )

@app.route("/practice-interview-question/<int:index>", methods=["GET"])
@login_required # Ensures that only authenticated users can access this route
def practice_interview_question(index):
    """
    AJAX endpoint to serve a specific question for practice.
    Retrieves from the DB session, generating new questions if needed.
    """
    # Fetch the current practice session ID from the Flask session
    practice_session_id = session.get("current_practice_session_id")
    # Return an error if no active practice session ID is found
    if not practice_session_id:
        return jsonify({"error": "No active practice session found. Please start a new one."}), 400
    
    # Retrieve the PracticeSession object from the database
    current_practice_session = PracticeSession.query.get(practice_session_id)
    # Validate that the session exists and is of the 'practice' type
    if not current_practice_session or current_practice_session.session_type != 'practice':
        return jsonify({"error": "Practice session not found in database or invalid type. Please start a new one."}), 400

    # Parse questions data from the JSON string stored in the database entry
    questions = json.loads(current_practice_session.questions_data)
    
    # Extract job details from the current practice session object for AI prompting
    job_details = {
        "position": current_practice_session.job_position,
        "experience": current_practice_session.experience_level,
        "industry": current_practice_session.industry
    }

    # Return an error if the AI service (model) is not initialized
    if model is None:
        return jsonify({"error": "AI service not available."}), 500

    # If the requested question index already exists in the session's data
    if 0 <= index < len(questions):
        logging.info(f"Returning existing practice question at index {index}.")
        # Return the question and its associated data as JSON
        return jsonify({
            "question": questions[index]["question"],
            "index": index,
            "total": MAX_PRACTICE_QUESTIONS # Indicate the total number of questions for practice
        })
    # If the requested index is the next one in sequence, indicating a new question is needed
    elif index == len(questions): 
        # Check if the maximum number of practice questions has been reached
        if len(questions) >= MAX_PRACTICE_QUESTIONS:
            logging.info(f"Attempted to generate practice question {index}, but max limit ({MAX_PRACTICE_QUESTIONS}) reached.")
            return jsonify({"error": "Maximum practice questions reached."}), 400

        logging.info(f"Generating new practice question for index {index}...")
        try:
            previous_questions_text = ""
            # If there are existing questions, include them in the prompt to ensure uniqueness
            if questions:
                # Prepare a list of previously asked questions for the AI prompt
                previous_q_for_prompt = [q['question'] for q in questions]
                previous_questions_text = "Here are questions that have already been asked (ensure your new question is unique):\n" + "\n".join([f"- {q}" for q in previous_q_for_prompt]) + "\n\n"

            # Construct the prompt for the Gemini model to generate a unique interview question
            prompt = f"""
            {previous_questions_text}
            Generate 1 distinct, new interview question and its concise, ideal answer for a {job_details['experience']} {job_details['position']} position{f' in the {job_details['industry']} industry' if job_details['industry'] else ''}.
            This new question MUST be UNIQUE and DIFFERENT from any of the previously listed questions.
            The answer should be no more than 3-5 sentences.
            Ensure the question and answer pair follows this strict format:
            Question: [Your unique question here]
            Answer: [Your ideal answer here]
            """
            
            # Call the Gemini API to generate content
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=500, # Limit the length of the AI's response
                    temperature=0.7, # Control the creativity of the AI's response
                ),
                request_options={'timeout': 90} # Set a timeout for the API request
            )
            raw_text = response.text.strip()
            logging.info(f"Gemini API call completed for practice question {index}.")
            logging.debug(f"Raw text from Gemini (practice question {index}):\n{raw_text[:500]}...")

            # Parse the AI's raw text response into a structured Q&A pair
            parsed_qa = parse_ai_response(raw_text)

            # If a valid question and answer pair was successfully parsed
            if parsed_qa:
                new_qa = parsed_qa[0]
                
                # Append the new Q&A pair to the list of questions
                questions.append(new_qa)
                # Update the questions_data field in the database object with the new JSON string
                current_practice_session.questions_data = json.dumps(questions)
                # Commit the changes to the database
                db.session.commit()

                logging.info(f"New Q&A pair generated and stored for practice index {index} in DB.")
                # Return the newly generated question as JSON
                return jsonify({
                    "question": new_qa["question"],
                    "index": index,
                    "total": MAX_PRACTICE_QUESTIONS
                })
            else:
                logging.warning(f"No valid Q&A pair parsed from AI response for new practice question at index {index}. Raw: {raw_text[:200]}")
                return jsonify({"error": "Failed to generate a new practice question. AI response was malformed."}), 500

        # Handle API timeout errors during question generation
        except DeadlineExceeded as e:
            logging.error(f"Gemini API Timeout for practice question {index}: {e}")
            return jsonify({"error": "AI generation timed out for this practice question. Please try again."}), 504
        # Handle general Google API errors during question generation
        except GoogleAPIError as e:
            logging.error(f"Google Gemini API Error for practice question {index}: {e}")
            return jsonify({"error": f"AI Service Error for this practice question: {e}"}), 500
        # Catch any other unexpected exceptions during the process
        except Exception as e:
            logging.critical(f"An unexpected error occurred generating practice question {index}: {e}", exc_info=True)
            return jsonify({"error": "An unexpected server error occurred while fetching this practice question."}), 500
    # If an invalid question index is requested
    else:
        logging.warning(f"Invalid practice question index requested: {index}.")
        return jsonify({"error": "Invalid practice question index requested."}), 404

@app.route("/practice-evaluate", methods=["POST"])
@login_required # Ensures that only authenticated users can access this route
def practice_evaluate():
    """
    AJAX endpoint to receive user's answer, send it to the AI for evaluation,
    and store the result in the database. Returns AI feedback for immediate display.
    """
    # Fetch the current practice session ID from the Flask session
    practice_session_id = session.get("current_practice_session_id")
    # Redirect if no session ID is found (e.g., session cookie lost)
    if not practice_session_id:
        flash("No active practice session found. Please start a new practice interview.", "info")
        return jsonify({"redirect": url_for('practice_interview')}), 400
    
    # Retrieve the PracticeSession object from the database
    current_practice_session = PracticeSession.query.get(practice_session_id)
    # Redirect if the session is not found in DB or its type is invalid
    if not current_practice_session or current_practice_session.session_type != 'practice':
        flash("Practice session not found in database or invalid type. Please start a new practice interview.", "error")
        return jsonify({"redirect": url_for('practice_interview')}), 400

    # Parse the existing questions data from the database
    questions_data_list = json.loads(current_practice_session.questions_data)
    
    # Get the JSON data sent in the request body
    data = request.get_json()
    # Extract the question index and the user's answer from the JSON data
    q_index = data.get("index")
    user_answer = data.get("user_answer", "").strip()

    # Validate the question index
    if q_index is None or not isinstance(q_index, int) or not (0 <= q_index < MAX_PRACTICE_QUESTIONS):
        return jsonify({"error": "Invalid question index for evaluation."}), 400

    # Validate that the user's answer is not empty
    if not user_answer:
        return jsonify({"error": "Your answer cannot be empty. Please provide a response."}), 400

    # Ensure the requested question index exists in the loaded data
    if q_index >= len(questions_data_list):
        logging.error(f"Evaluation requested for non-existent question index in loaded data: {q_index}")
        return jsonify({"error": "Question data not found for evaluation."}), 404
    
    # Retrieve the question text and ideal answer for evaluation
    question_text = questions_data_list[q_index]["question"]
    ideal_answer = questions_data_list[q_index]["answer"] 
    
    # Extract job details from the current practice session for context in AI evaluation
    job_details = {
        "position": current_practice_session.job_position,
        "experience": current_practice_session.experience_level,
        "industry": current_practice_session.industry
    }

    # Return an error if the AI model is not available
    if model is None:
        return jsonify({"error": "AI service not available."}), 500

    logging.info(f"Evaluating user answer for question index {q_index}...")
    try:
        context_phrase = ""
        # Add job context to the prompt if available
        if job_details.get("position"):
            context_phrase = f" for a \"{job_details['experience']} {job_details['position']}\" interview question"

        # Construct the prompt for the AI to evaluate the user's answer
        evaluation_prompt = f"""
        As an expert interview coach, evaluate the following user's answer{context_phrase}.
        Provide concise, actionable feedback focusing ONLY on areas for improvement. Do NOT just rephrase the ideal answer.
        Limit your feedback to 3-5 sentences.
        Interview Question: {question_text}
        User's Answer: {user_answer}
        Ideal Answer: {ideal_answer}
        Feedback:
        """
        # Call the Gemini API for evaluation
        response = model.generate_content(
            evaluation_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=300, # Limit the feedback length
                temperature=0.5, # Control creativity for more factual feedback
            ),
            request_options={'timeout': 60} # Set a timeout for the API request
        )
        feedback_text = response.text.strip()
        logging.info(f"AI feedback generated for question {q_index}.")
        logging.debug(f"Raw feedback from Gemini:\n{feedback_text[:300]}...")

        # Update the specific question entry in the list with the user's answer and AI feedback
        if q_index < len(questions_data_list):
            questions_data_list[q_index].update({ 
                "user_answer": user_answer,
                "ai_feedback": feedback_text
            })
        else:
            # Fallback for unexpected scenarios, append a new entry if index is out of bounds
            questions_data_list.append({
                "question": question_text,
                "answer": ideal_answer, # Include ideal answer to maintain data structure
                "user_answer": user_answer,
                "ai_feedback": feedback_text
            })
            logging.warning(f"Appended new entry for q_index {q_index} as it was out of bounds for existing data.")
            
        # Store the updated questions data list back into the database for the current session
        current_practice_session.questions_data = json.dumps(questions_data_list)
        # Commit the changes to the database
        db.session.commit()
        logging.info(f"Stored practice data for question {q_index} in DB.")

        # Check if all practice questions have been evaluated
        if len(questions_data_list) == MAX_PRACTICE_QUESTIONS: 
            logging.info("All practice questions evaluated. Redirecting to practice results page.")
            return jsonify({"redirect": url_for('practice_results')})
        else:
            logging.info(f"Evaluation for question {q_index} complete. Sending feedback.")
            # Return the AI feedback to the client for immediate display
            return jsonify({
                "message": "Answer evaluated successfully.",
                "feedback": feedback_text
            })

    # Handle API timeout errors during evaluation
    except DeadlineExceeded as e:
        logging.error(f"Gemini API Timeout for evaluation of question {q_index}: {e}")
        return jsonify({"error": "AI evaluation timed out. Please try again."}), 504
    # Handle general Google API errors during evaluation
    except GoogleAPIError as e:
        logging.error(f"Google Gemini API Error for evaluation of question {q_index}: {e}")
        return jsonify({"error": f"AI Service Error during evaluation: {e}"}), 500
    # Catch any other unexpected errors
    except Exception as e:
        logging.critical(f"An unexpected error occurred during evaluation of question {q_index}: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred during evaluation."}), 500

@app.route("/practice-results")
@login_required # Ensures that only authenticated users can access this route
def practice_results():
    """
    Displays the aggregated results of the practice interview, including overall AI feedback.
    """
    # Retrieve the current practice session ID from the Flask session
    practice_session_id = session.get("current_practice_session_id")
    # Redirect if no active practice session ID is found
    if not practice_session_id:
        flash("No active practice session found to display results. Please start a new practice interview.", "info")
        return redirect(url_for('practice_interview'))

    # Retrieve the PracticeSession object from the database
    current_practice_session = PracticeSession.query.get(practice_session_id)
    # Redirect if the session is not found in DB or its type is invalid
    if not current_practice_session or current_practice_session.session_type != 'practice':
        flash("Practice session results not found in database or invalid type. Please start a new practice interview.", "error")
        return redirect(url_for('practice_interview'))

    # Load the practice data (questions, user answers, feedback) from the database object
    practice_data = json.loads(current_practice_session.questions_data)
    
    # Extract job details from the current practice session for context in results display
    job_details = {
        "position": current_practice_session.job_position,
        "experience": current_practice_session.experience_level,
        "industry": current_practice_session.industry
    }

    # If practice data is incomplete, inform the user and redirect
    if not practice_data or len(practice_data) < MAX_PRACTICE_QUESTIONS:
        flash("Practice session incomplete. Please finish a practice interview first.", "info")
        return redirect(url_for('practice_interview'))

    logging.info("Generating overall feedback for practice results.")
    # Generate overall feedback for the entire practice session
    overall_feedback = generate_overall_practice_feedback(practice_data, job_details)

    # Clear session data related to this specific practice interview after results are displayed
    session.pop("current_practice_session_id", None)
    session.pop("job_details", None) # Clear job details specific to this practice session
    session.modified = True # Ensure session changes are persisted

    # Render the practice results template, passing the practice data, overall feedback, and job details
    return render_template(
        "practice_results.html",
        practice_data=practice_data,
        overall_feedback=overall_feedback,
        job_details=job_details 
    )


@app.route("/resume-optimizer", methods=["GET", "POST"]) # Route configured to handle both GET and POST requests
@login_required # Ensures only logged-in users can access this feature
def resume_optimizer():
    """
    Displays the form for users to submit their resume and job description (GET).
    Processes the resume optimization request and stores results in the database (POST).
    """
    # Handle POST requests for resume optimization submission
    if request.method == "POST":
        logging.info("POST request received for /resume-optimizer (resume optimization).")
        # Get the user ID from the session; redirect if not logged in
        user_id = session.get('user_id')
        if not user_id:
            flash("User not logged in.", "error")
            return redirect(url_for('login'))

        # Retrieve resume text and job description from the submitted form
        resume_text = request.form.get("resume_text")
        job_description = request.form.get("job_description")

        # Validate that both resume text and job description are provided
        if not resume_text or not job_description:
            flash("Both resume text and job description are required for optimization.", "error")
            # Re-render the setup form with an error message and pre-fill inputs
            return render_template("resume_optimizer_setup.html", resume_text=resume_text, job_description=job_description)

        # Check if the Gemini AI model is initialized
        if model is None:
            flash("Google Gemini AI client not initialized. Check API key in .env and restart server.", "error")
            return render_template("error.html", message="AI service not available for resume optimization. Check terminal for details.", go_back_url=url_for('resume_optimizer'))

        logging.info("Calling Gemini API for resume optimization...")
        try:
            # Construct the comprehensive prompt for resume optimization
            prompt = f"""
            As an expert resume optimizer, analyze the provided resume against the job description.
            First, provide a **Match Score:** (e.g., 75%).
            Then, provide a **Summary Message:** explaining the overall match and areas for improvement of the ORIGINAL resume.
            Next, list **Original Resume Analysis - Areas for Improvement:** using bullet points. Be specific and actionable.
            Then, provide an **Optimized Resume:** based on the original, tailored to the job description, ensuring it's a complete and well-formatted resume.
            Finally, provide an **Analysis of Optimization Changes:** explaining what changes were made and why.

            Ensure all section headers are bolded using double asterisks (e.g., **Match Score:**).

            Job Description:
            {job_description}

            Resume:
            {resume_text}
            """
            
            # Call the Gemini API to generate the resume optimization
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=2000, # Increased token limit to accommodate full resume and analysis
                    temperature=0.7, # Control the creativity of the AI response
                ),
                request_options={'timeout': 180} # Set a longer timeout for complex generation
            )
            raw_text = response.text.strip()
            logging.info("Gemini API call completed for resume optimization.")
            
            # Use the dedicated parsing function to extract structured results from the AI's response
            parsed_results = parse_resume_optimization_response(raw_text)

            # Check for insufficient or failed parsing of AI results
            if parsed_results['match_score'] == 'N/A' and not parsed_results['original_improvements'] and parsed_results['optimized_resume_text'] == 'Could not generate optimized resume.':
                logging.warning("Resume optimization parsing incomplete or failed. Full AI response:\n%s", raw_text)
                flash("AI did not generate a complete resume optimization. Please try again with different inputs or wait for a moment.", "error")
                return render_template("error.html", message="AI did not generate complete optimization results. Check terminal for details.", go_back_url=url_for('resume_optimizer'))

            # Create a new ResumeOptimizationResult object and populate it with parsed data
            new_result = ResumeOptimizationResult(
                user_id=user_id,
                match_score=parsed_results['match_score'],
                summary_message=parsed_results['summary_message'],
                original_improvements="\n".join(parsed_results['original_improvements']), # Convert list to newline-separated string for storage
                optimized_resume_text=parsed_results['optimized_resume_text'],
                changes_analysis=parsed_results['changes_analysis']
            )
            # Add the new result to the database session
            db.session.add(new_result)
            # Commit the transaction to save the results to the database
            db.session.commit()
            logging.info(f"Resume optimization results for user {user_id} stored in database.")

            flash("Resume optimization completed successfully!", "success")
            # Redirect to the results display page after successful optimization
            return redirect(url_for('resume_optimizer_results'))

        # Handle API timeout errors during resume optimization
        except DeadlineExceeded as e:
            logging.error(f"Gemini API Timeout during resume optimization: {e}")
            flash(f"AI generation timed out during resume optimization. Please try again. Details: {e}", "error")
            return render_template("error.html", message="AI generation timed out for resume optimization. Please try again.", go_back_url=url_for('resume_optimizer'))
        # Handle general Google API errors during resume optimization
        except GoogleAPIError as e:
            logging.error(f"Google Gemini API Error during resume optimization: {e}")
            flash(f"Failed to optimize resume from AI due to an API error: {e}. Check API key or Google Cloud console for issues.", "error")
            return render_template("error.html", message=f"AI Service Error: {e}", go_back_url=url_for('resume_optimizer'))
        # Catch any other unexpected errors during the process
        except Exception as e:
            logging.critical(f"An unexpected error occurred during resume optimization: {e}", exc_info=True)
            flash("An unexpected server error occurred during resume optimization. Please try again.", "error")
            return render_template("error.html", message="An unexpected server error occurred. Please try again. Check terminal for details.", go_back_url=url_for('resume_optimizer'))

    # Handle GET requests: display the resume optimization setup form
    else: 
        logging.info("GET request received for /resume-optimizer. Rendering resume_optimizer_setup.html.")
        return render_template("resume_optimizer_setup.html")


@app.route("/resume-optimizer-results")
@login_required # Ensures only logged-in users can access their results
def resume_optimizer_results():
    """
    Displays the stored resume optimization results for the current user.
    """
    # Get the user ID from the session; redirect if not logged in
    user_id = session.get('user_id')
    if not user_id:
        flash("Please log in to view resume optimization results.", "warning")
        return redirect(url_for('login', next=request.url))

    # Fetch the latest resume optimization results for the current user from the database
    results = ResumeOptimizationResult.query.filter_by(user_id=user_id).order_by(ResumeOptimizationResult.timestamp.desc()).first()

    # If no results are found, inform the user and redirect to the optimizer setup page
    if not results:
        flash("No resume optimization results found. Please run the optimizer first.", "info")
        return redirect(url_for('resume_optimizer'))
    
    # Reconstruct the 'original_improvements' list from the stored string (newline-separated)
    if results.original_improvements:
        results.original_improvements = results.original_improvements.split('\n')
    else:
        results.original_improvements = [] # Ensure it's an empty list if no improvements were stored

    # Render the resume optimizer results template, passing the fetched results
    return render_template("resume_optimizer_results.html", results=results)


# Entry point for the Flask application
if __name__ == '__main__':
    # Ensure the 'templates' directory exists for Flask to find HTML files
    if not os.path.exists('templates'):
        os.makedirs('templates')
    # Run the Flask application in debug mode for development purposes
    # In production, a more robust WSGI server (e.g., Gunicorn, uWSGI) should be used
    app.run(debug=True)