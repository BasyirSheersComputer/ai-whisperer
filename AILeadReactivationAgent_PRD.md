# Product Requirements Document (PRD): AI Lead Reactivation Agent

## 1. Product Overview

**Name:** AI Lead Reactivation Agent
**Target Audience:** Local, traditional brick-and-mortar businesses (gyms, med spas, dentists, chiropractors, roofers, HVAC, etc.).
**Core Value Proposition:** To act as an automated "AI employee" that plugs into a business's existing, dormant database of leads. It proactively reaches out to these cold leads via SMS, re-engages them, qualifies them, and drives them back into the business's sales pipeline without requiring human staff intervention or new marketing ad spend.
**Problem Solved:** On average, business owners only follow up with 27% of new leads. This leaves massive amounts of potential revenue sitting untouched in databases collecting dust.

## 2. Core Workflows & Logic

The system must operate autonomously based on a state machine that handles the progression of a lead from a cold state to a booked appointment.

### Phase 1: Database Ingestion & Segmentation

* **Data Import:** The system must accept CSV uploads or connect via API (e.g., Zapier/Make) to the client's existing CRM to ingest dormant leads. Required fields include Name, Phone Number, and potentially Last Contact Date.
* **Opt-In/Compliance Check:** Ensure leads have not previously opted out of SMS communications.

### Phase 2: Initial Outreach (The "Hook")

* **Trigger:** The system initiates contact based on a scheduled drip campaign to avoid overwhelming the business's capacity.
* **Channel:** Strictly SMS.
* **Message Generation:** The LLM generates a personalized, casual, and non-salesy opening message designed solely to elicit a response (e.g., "Hey [Name], it's [Business Name]. We're running a special for past contacts this week. Are you still looking to [solve specific problem]?").

### Phase 3: Conversational Engagement & Qualification

* **Response Handling:** When a lead replies, the LLM analyzes the intent (Positive, Negative, Question, Opt-Out).
* **Opt-Out Logic:** If the intent is negative (e.g., "Stop", "Not interested"), the system immediately ceases contact, updates the CRM status to 'Dead/Opt-Out', and sends a compliance acknowledgment.
* **Conversational Logic:** If the intent is positive or questioning, the LLM engages in a back-and-forth conversation.
* **Goal:** Guide the user toward booking an appointment.
* **Context:** The LLM must be loaded with the business's specific FAQs, pricing, operating hours, and current offers to answer questions accurately.



### Phase 4: Conversion & Handoff

* **Scheduling Integration:** The system must integrate with the business's calendar system (e.g., Calendly, GoHighLevel calendar).
* **Booking Prompt:** Once the lead expresses readiness, the AI provides a booking link or offers specific times based on live calendar availability.
* **Confirmation:** Upon successful booking, the AI sends a confirmation SMS.
* **Human Handoff:** If the AI encounters a complex question it cannot answer or the user explicitly requests a human, it pauses the automation and sends an alert to the business staff (via email or CRM notification).

## 3. Technical Architecture & Tech Stack

This architecture is designed for a scalable, multi-tenant SaaS or agency model.

### 3.1. Infrastructure

* **Backend Framework:** Python (FastAPI) or Node.js (Express) for robust API handling.
* **Database:** PostgreSQL for relational data (users, businesses, configurations) and a NoSQL database (like MongoDB or Firebase) for storing conversation logs and unstructured lead data.
* **Task Queues:** Redis/Celery for handling background tasks, scheduling messages, and managing rate limits.

### 3.2. Core Integrations

* **LLM Engine:** OpenAI API (GPT-4o or similar) or Anthropic API (Claude 3.5 Sonnet) for handling conversational logic.
* **Telephony/SMS:** Twilio API or Plivo for programmatic SMS sending and receiving. Requires robust handling of A2P 10DLC compliance (crucial for US numbers).
* **Calendar Sync:** Nylas API or direct integrations (Google Calendar, Outlook) for checking real-time availability.
* **CRM/Workflow Connectors:** Webhooks and API endpoints that allow easy connection to Make.com or Zapier, enabling integration with the client's specific CRM (e.g., GoHighLevel, Hubspot).

## 4. Prompt Engineering & LLM Context Rules

The system's intelligence relies on highly structured system prompts. The LLM must be configured with a specific persona and strict operational boundaries.

### Core Persona Rules:

1. **Identity:** Act as an enthusiastic, helpful human assistant working for [Client Business Name]. Never disclose that you are an AI.
2. **Brevity:** Keep SMS messages short (under 160 characters when possible). Speak casually. Avoid formal corporate jargon.
3. **Objective:** Your primary goal is to guide the user to book an appointment or claim the current offer.
4. **Boundary Constraints:** Do not invent pricing, medical advice, or specific guarantees. If asked a question outside your provided knowledge base, respond politely that you need to check with the team and trigger a human handoff.

### Dynamic Context Injection:

For every incoming message, the system must inject the following context into the LLM prompt:

* Lead Details: `Name`, `Past Interaction History`
* Business Profile: `Business Name`, `Industry`, `Core Offer`, `FAQ document`
* Current Goal: `Get the user to click [Booking Link]`

## 5. Development Milestones & Instructions for Claude

Please proceed with development in the following sequence. Ask for clarification before starting a new milestone.

1. **Milestone 1: Environment Setup & Twilio Integration:** Create the backend structure. Set up the Twilio webhooks to handle incoming and outgoing SMS. Create a dummy endpoint to simulate a user sending an SMS.
2. **Milestone 2: LLM Engine & State Machine:** Build the core logic. Integrate the LLM API. Create the system prompts and implement the conversational loop. Ensure the system can correctly identify "Opt-out" intent versus a question.
3. **Milestone 3: Data Ingestion & CRM:** Build the database schemas for storing leads and conversation history. Implement an API endpoint to ingest a list of leads via CSV upload or webhook.
4. **Milestone 4: Scheduling & Outbound Logic:** Integrate a mock calendar system to handle availability. Build the CRON jobs/task queues to handle the initial outbound blasts at a throttled rate (e.g., 50 messages per hour to avoid spam flags).
5. **Milestone 5: Multi-Tenancy & UI (Optional but recommended):** Structure the database to handle multiple client businesses, each with their own Twilio numbers, system prompts, and knowledge bases.