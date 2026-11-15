# Pramaan — 3-Minute Prototype Video Walkthrough Script

**Target Duration:** 3 minutes (180 seconds)  
**Tone:** Confident, problem-focused, crisp, and fast-paced  
**Setup Checklist Before Recording:**
- Browser opened to the Pramaan login screen (`/login`).
- Browser window maximized (1080p, 100% zoom).
- Audio microphone tested.

---

## Timeline Overview

| Time | Segment | Core Focus |
|---|---|---|
| **0:00 – 0:30** | Hook & The Circular Crisis | The problem of messy, contradictory PDFs & missed deadlines |
| **0:30 – 1:15** | Student Experience | Context Bar, Live Deadlines, What Changed Feed, Grounded Chatbot |
| **1:15 – 2:15** | Admin Studio & Conflict Resolution | Upload extraction, resolving Notice #18 vs #19 contradiction, 1-click publish |
| **2:15 – 3:00** | Architectural Moat & Impact | PyMuPDF parsing, 4 Truth States, zero-hallucination guarantee, wrap-up |

---

## Detailed Scene-by-Scene Script

### Scene 1: Hook & The Problem (0:00 – 0:30)

| Time | On-Screen Action | Voiceover (What to Say) |
|---|---|---|
| **0:00 – 0:10** | Show the **Login Screen**. Hover cursor over Google Login and Demo buttons. | *"Every semester, universities release dozens of circulars across notice boards, portals, and WhatsApp groups. The result? Total chaos. Dates change, fees get revised, circulars contradict one another, and students miss critical deadlines."* |
| **0:10 – 0:20** | Click **"Demo: Continue as Student"**. | *"Standard AI chatbots hallucinate or cite expired circulars because they lack temporal awareness. Meet **Pramaan** — the deterministic truth ledger and conflict-resolution engine for college circulars."* |
| **0:20 – 0:30** | Land on the **Student Dashboard**. | *"Pramaan turns unstructured PDFs into a real-time, verified ground-truth feed with 100% page-level citations."* |

---

### Scene 2: Student Experience & Grounded Truth (0:30 – 1:15)

| Time | On-Screen Action | Voiceover (What to Say) |
|---|---|---|
| **0:30 – 0:45** | Highlight the **Context Bar** (Course: B.Sc Data Science, Sem 4). Move cursor across the **Next Deadlines Strip** with countdown badges. | *"Here is the student dashboard. It automatically scopes notices to my course and semester. At the top, the **Deadline Strip** calculates real-time urgency countdowns, and with one click, I can sync any deadline directly to my calendar."* |
| **0:45 – 0:58** | Scroll smoothly to **"What changed for you"**. Point to the strikethrough badge (`Rs. 50 ➔ Rs. 75`). Click the button: **`Notice 12 Nov, page 2`**. | *"Notice this section: **What changed for you**. Instead of reading a 10-page circular, students see instant diffs — like late fee revised from Rs. 50 to Rs. 75. Clicking the badge opens the **Source Drawer**, showing the exact circular and highlighted sentence for definitive proof."* |
| **0:58 – 1:15** | Close drawer. Click the floating **"Ask Pramaan"** button. Type or click: *"What is the late fee?"* | *"Now let's ask the chatbot: 'What is the late fee?' Notice the response: Pramaan doesn't give a vague summary. It returns a **Verified Green State** with Rs. 75, notes that it supersedes the November 10th circular, and links the verified page citation."* |

---

### Scene 3: Admin Truth Studio & Conflict Resolution (1:15 – 2:15)

| Time | On-Screen Action | Voiceover (What to Say) |
|---|---|---|
| **1:15 – 1:30** | Click Logout / switch to `/login` and click **"Demo: Continue as Admin"**. | *"Now, where does this truth come from? Let's switch to the **Admin Studio**. Administrators get an automated pipeline that extracts atomic facts from uploaded PDFs."* |
| **1:30 – 1:50** | Click on the **Conflicts card** (showing 1 Conflict). Show the conflict between **Notice #18 and Notice #19** (9:00 AM vs 2:00 PM lab exam). Click **Resolve Conflict**. Select **Notice #19 (2:00 PM)**. | *"Here is Pramaan's core superpower: **Automated Conflict Detection**. Notice #18 scheduled lab exams at 9:00 AM, but Notice #19 rescheduled them to 2:00 PM. Instead of confusing students, Pramaan flags the contradiction for admin review. I simply select Notice #19 as the winning circular and confirm."* |
| **1:50 – 2:05** | Approve remaining pending facts. Click the big **"Publish Approved Facts"** button. Watch the confetti burst! | *"With the conflict resolved, I review the pending facts, approve them, and hit **Publish**. Instantly, the old facts are archived as 'superseded' and the new ledger goes live to thousands of students."* |
| **2:05 – 2:15** | Scroll down to **Unanswered Questions**. Click on *"Re-exam date?"*, type an answer, and click **Save Fact**. | *"Administrators can also see queries students asked that weren't in official records. With one click, an admin can answer it, turning unanswered student questions into instant verified ground truth."* |

---

### Scene 4: Architecture, Moat & Closing (2:15 – 3:00)

| Time | On-Screen Action | Voiceover (What to Say) |
|---|---|---|
| **2:15 – 2:35** | Switch back to the **Student Portal**. Ask *"What is the lab exam time?"* ➔ show it now says 2:00 PM. | *"Under the hood, Pramaan combines **PyMuPDF extraction**, **temporal conflict analysis**, and a **deterministic 4-state classifier**: Verified, Outdated, Disputed, or Unavailable. If an answer isn't backed by an authorized circular, Pramaan refuses to guess."* |
| **2:35 – 2:50** | Show responsive layout / mobile view or smooth scroll through the dashboard. | *"The frontend is built with React 18, TypeScript, and Tailwind, backed by a high-throughput Python FastAPI service with an append-only audit trail for institutional compliance."* |
| **2:50 – 3:00** | Return to the clean home screen. Camera / presenter view for final punchline. | *"Pramaan eliminates the circular crisis, protects colleges from misinformation, and guarantees students never miss a deadline again. Thank you!"* |
