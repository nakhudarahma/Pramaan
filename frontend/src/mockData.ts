import type {
  Deadline,
  ChangeItem,
  NoticeRecord,
  FactRow,
  UnansweredItem,
  CourseId,
  Semester,
} from "./types";
import { COURSES, SEMESTERS } from "./types";

// Initial seed data. These are the defaults that get written to localStorage
// when the demo starts or is reset.

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatDate(date: Date): string {
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

function daysLeftFromToday(date: Date): number {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.max(0, Math.round((target.getTime() - today.getTime()) / 86_400_000));
}

const DEADLINE_TITLES = [
  "Fee payment",
  "Exam form",
  "Project submission",
  "Practical registration",
  "Hall ticket collection",
  "Scholarship application",
  "Internal marks challenge",
];

// Base dates within Nov–Dec 2026.
const DEADLINE_BASE_DATES = [
  new Date(2026, 10, 18),
  new Date(2026, 10, 22),
  new Date(2026, 10, 27),
  new Date(2026, 11, 4),
  new Date(2026, 11, 9),
];

function buildDeadlines(): Deadline[] {
  const rows: Deadline[] = [];

  COURSES.forEach((course, ci) => {
    SEMESTERS.forEach((sem, si) => {
      const firstTitle = (ci + si) % DEADLINE_TITLES.length;

      DEADLINE_BASE_DATES.forEach((base, i) => {
        const date = new Date(base);
        date.setDate(base.getDate() + ((ci * 2 + si + i) % 5));

        rows.push({
          id: `d-${course.id}-${sem}-${i}`,
          title: DEADLINE_TITLES[(firstTitle + i) % DEADLINE_TITLES.length],
          date: formatDate(date),
          daysLeft: daysLeftFromToday(date),
          course: course.id,
          semester: sem,
        });
      });
    });
  });

  return rows;
}

export const seedDeadlines: Deadline[] = buildDeadlines();

const CHANGE_TEMPLATES = [
  {
    label: "Exam form deadline",
    oldValue: "25 Nov 2026",
    newValue: "30 Nov 2026",
    factId: "f-examform",
    noticeTitle: "Notice 10 Nov",
    page: 1,
  },
  {
    label: "Late fee",
    oldValue: "Rs. 50",
    newValue: "Rs. 75",
    factId: "f-latefee-new",
    noticeTitle: "Notice 12 Nov",
    page: 2,
  },
];

function buildChanges(): ChangeItem[] {
  const rows: ChangeItem[] = [];

  COURSES.forEach((course, ci) => {
    SEMESTERS.forEach((sem, si) => {
      // Keep the B.Sc Data Science, Sem 4 demo scenario intact.
      if (course.id === "bsc-ds" && sem === 4) {
        rows.push({
          id: "c-bsc-ds-4-latefee",
          label: "Late fee",
          oldValue: "Rs. 50",
          newValue: "Rs. 75",
          noticeDate: "12 Nov 2026",
          factId: "f-latefee-new",
          noticeTitle: "Notice 12 Nov",
          page: 2,
          course: course.id,
          semester: sem,
          approved: true,
        });
        rows.push({
          id: "c-bsc-ds-4-examform",
          label: "Exam form deadline",
          oldValue: "25 Nov 2026",
          newValue: "30 Nov 2026",
          noticeDate: "10 Nov 2026",
          factId: "f-examform",
          noticeTitle: "Notice 10 Nov",
          page: 1,
          course: course.id,
          semester: sem,
          approved: true,
        });
        rows.push({
          id: "c-bsc-ds-4-feewindow",
          label: "Fee payment window",
          oldValue: "20 Nov 2026",
          newValue: "26 Nov 2026",
          noticeDate: "10 Nov 2026",
          factId: "f-feewindow",
          noticeTitle: "Notice 10 Nov",
          page: 1,
          course: course.id,
          semester: sem,
          approved: true,
        });
        rows.push({
          id: "c-bsc-ds-4-canteen",
          label: "Canteen thali price",
          oldValue: "Rs. 50",
          newValue: "Rs. 60",
          noticeDate: "05 Nov 2026",
          factId: "f-canteen",
          noticeTitle: "Notice 05 Nov",
          page: 1,
          course: course.id,
          semester: sem,
          approved: true,
        });
        rows.push({
          id: "c-bsc-ds-4-bus",
          label: "Bus Route 7A pick-up (Andheri)",
          oldValue: "7:15 AM",
          newValue: "7:00 AM",
          noticeDate: "06 Nov 2026",
          factId: "f-bus",
          noticeTitle: "Notice 06 Nov",
          page: 1,
          course: course.id,
          semester: sem,
          approved: true,
        });
        return;
      }

      const count = (ci + si) % 2 === 0 ? 1 : 2;

      for (let i = 0; i < count; i++) {
        const template =
          CHANGE_TEMPLATES[(ci + si + i) % CHANGE_TEMPLATES.length];
        rows.push({
          id: `c-${course.id}-${sem}-${i}`,
          label: template.label,
          oldValue: template.oldValue,
          newValue: template.newValue,
          noticeDate: i === 0 ? "10 Nov 2026" : "12 Nov 2026",
          factId: template.factId,
          noticeTitle: template.noticeTitle,
          page: template.page,
          course: course.id,
          semester: sem,
          approved: true,
        });
      }
    });
  });

  return rows;
}

export const seedChanges: ChangeItem[] = buildChanges();

export const seedNotices: NoticeRecord[] = [
  {
    id: "n14",
    title: "Annual Sports Day — Call for Entries",
    issuer: "Principal's Office",
    date: "13 Nov 2026",
    page: 1,
    status: "current",
    category: "Activities",
    noticeNumber: "PRM/2026/014",
    body: "Students interested in participating in the Annual Sports Day on 5 December 2026 must register with the Sports Office by 25 November 2026. Team events require a minimum of four participants.",
    highlightedSentence:
      "must register with the Sports Office by 25 November 2026",
  },
  {
    id: "n12",
    title: "Revised Late Fee Circular — November 2026",
    issuer: "Accounts Office",
    date: "12 Nov 2026",
    page: 2,
    status: "current",
    category: "Fees",
    noticeNumber: "PRM/2026/012",
    replaces: "Notice 10 Nov",
    body: "Pursuant to the earlier circular dated 10 November 2026, the late fee has been revised to Rs. 75 for all late fee payments. This supersedes the previous circular. Applies to B.Sc Data Science Semester 4 students.",
    highlightedSentence:
      "the late fee has been revised to Rs. 75 for all late fee payments",
  },
  {
    id: "n19",
    title: "Revised Lab Examination Timings",
    issuer: "Exam Cell",
    date: "11 Nov 2026",
    page: 1,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/019",
    replaces: "Notice 08 Nov",
    body: "The laboratory examinations for Semester 4 will now be conducted from 2:00 PM to 5:00 PM. Students should report to their labs by 1:45 PM.",
    highlightedSentence:
      "laboratory examinations for Semester 4 will now be conducted from 2:00 PM to 5:00 PM",
  },
  {
    id: "n10",
    title: "Late Fee Circular — November 2026",
    issuer: "Accounts Office",
    date: "10 Nov 2026",
    page: 1,
    status: "superseded",
    category: "Fees",
    noticeNumber: "PRM/2026/010",
    body: "This is to inform all students that a late fee of Rs. 50 will be charged for fee payments made after the due date of 20 November 2026. This applies to B.Sc Data Science Semester 4 students.",
    highlightedSentence:
      "a late fee of Rs. 50 will be charged for fee payments made after the due date of 20 November 2026",
  },
  {
    id: "n21",
    title: "Fee Payment Window Extended",
    issuer: "Accounts Office",
    date: "10 Nov 2026",
    page: 1,
    status: "current",
    category: "Fees",
    noticeNumber: "PRM/2026/021",
    body: "The fee payment window for Semester 4 has been extended to 26 November 2026. Students who have already paid need not take any action.",
    highlightedSentence:
      "The fee payment window for Semester 4 has been extended to 26 November 2026",
  },
  {
    id: "n16",
    title: "Practical Registration — Semester 4",
    issuer: "Exam Cell",
    date: "09 Nov 2026",
    page: 2,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/016",
    body: "Semester 4 students must complete practical registration by 4 December 2026. Registration is mandatory for all laboratory-based subjects.",
    highlightedSentence:
      "must complete practical registration by 4 December 2026",
  },
  {
    id: "n18",
    title: "Lab Examination Timings — Semester 4",
    issuer: "Exam Cell",
    date: "08 Nov 2026",
    page: 3,
    status: "superseded",
    category: "Exams",
    noticeNumber: "PRM/2026/018",
    body: "The laboratory examinations for Semester 4 will be conducted from 9:00 AM to 12:00 PM in the respective labs.",
    highlightedSentence:
      "laboratory examinations for Semester 4 will be conducted from 9:00 AM to 12:00 PM",
  },
  {
    id: "n08",
    title: "Library Fine Waiver Notice",
    issuer: "Principal's Office",
    date: "06 Nov 2026",
    page: 2,
    status: "expired",
    category: "General",
    noticeNumber: "PRM/2026/008",
    body: "Library fines accrued between 1 and 30 September 2026 may be waived if cleared by 10 November 2026. No further extensions will be granted.",
    highlightedSentence:
      "may be waived if cleared by 10 November 2026",
  },
  {
    id: "n25",
    title: "Exam Form Submission Deadline",
    issuer: "Exam Cell",
    date: "05 Nov 2026",
    page: 1,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/025",
    body: "All students of Semester 4 are required to submit their examination forms on or before 25 November 2026. Forms submitted after this date will not be accepted.",
    highlightedSentence:
      "submit their examination forms on or before 25 November 2026",
  },
  {
    id: "n05",
    title: "Admission Applications Open — 2027-28",
    issuer: "Principal's Office",
    date: "04 Nov 2026",
    page: 1,
    status: "current",
    category: "Admissions",
    noticeNumber: "PRM/2026/005",
    body: "Applications for undergraduate programmes for the 2027-28 academic year open on 1 December 2026. Applicants must complete the online form before 15 January 2027.",
    highlightedSentence:
      "Applications for undergraduate programmes for the 2027-28 academic year open on 1 December 2026",
  },
  {
    id: "n07",
    title: "Hostel Fee Payment Notice",
    issuer: "Accounts Office",
    date: "03 Nov 2026",
    page: 1,
    status: "current",
    category: "Hostel",
    noticeNumber: "PRM/2026/007",
    body: "Hostel fee for the current semester is due by 15 November 2026. This applies to Semester 1 and Semester 2 students only. Fee amount is Rs. 12,000.",
    highlightedSentence:
      "Hostel fee for the current semester is due by 15 November 2026",
  },
  {
    id: "n03",
    title: "Revised Semester 4 Timetable",
    issuer: "Exam Cell",
    date: "02 Nov 2026",
    page: 1,
    status: "current",
    category: "Timetable",
    noticeNumber: "PRM/2026/003",
    body: "The revised timetable for Semester 4 is effective from 16 November 2026. Practical batches will follow the lab schedule displayed on the department noticeboard.",
    highlightedSentence:
      "The revised timetable for Semester 4 is effective from 16 November 2026",
  },
  // =================== NEW NOTICES ===================
  {
    id: "n30",
    title: "Internal Assessment Marks Display",
    issuer: "Exam Cell",
    date: "13 Nov 2026",
    page: 1,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/030",
    body: "Internal assessment marks for Semester 4 subjects are now available on the student portal. Students who wish to challenge their marks must apply within 3 working days, i.e., by 18 November 2026.",
    highlightedSentence:
      "Students who wish to challenge their marks must apply within 3 working days",
  },
  {
    id: "n31",
    title: "Winter Break Schedule — December 2026",
    issuer: "Principal's Office",
    date: "12 Nov 2026",
    page: 1,
    status: "current",
    category: "General",
    noticeNumber: "PRM/2026/031",
    body: "The college will observe winter break from 22 December 2026 to 2 January 2027. All administrative offices will remain closed during this period. Last working day is 21 December 2026.",
    highlightedSentence:
      "winter break from 22 December 2026 to 2 January 2027",
  },
  {
    id: "n32",
    title: "Scholarship Application Deadline",
    issuer: "Student Welfare Office",
    date: "11 Nov 2026",
    page: 1,
    status: "current",
    category: "Scholarship",
    noticeNumber: "PRM/2026/032",
    body: "Students eligible for the National Merit Scholarship must submit their applications along with income certificates by 30 November 2026. Late applications will not be accepted under any circumstances.",
    highlightedSentence:
      "must submit their applications along with income certificates by 30 November 2026",
  },
  {
    id: "n33",
    title: "Anti-Ragging Committee — Awareness Session",
    issuer: "Dean of Students",
    date: "10 Nov 2026",
    page: 1,
    status: "current",
    category: "General",
    noticeNumber: "PRM/2026/033",
    body: "A mandatory anti-ragging awareness session will be conducted on 20 November 2026 at 10:00 AM in the auditorium. Attendance is compulsory for all first-year students.",
    highlightedSentence:
      "mandatory anti-ragging awareness session will be conducted on 20 November 2026",
  },
  {
    id: "n34",
    title: "ID Card Replacement — Last Batch",
    issuer: "Administration",
    date: "09 Nov 2026",
    page: 1,
    status: "current",
    category: "General",
    noticeNumber: "PRM/2026/034",
    body: "Students who have lost or damaged their ID cards may apply for a replacement by 22 November 2026. A fee of Rs. 200 is applicable. This is the last batch for the academic year.",
    highlightedSentence:
      "may apply for a replacement by 22 November 2026",
  },
  {
    id: "n35",
    title: "Guest Lecture — Machine Learning in Healthcare",
    issuer: "Department of Data Science",
    date: "08 Nov 2026",
    page: 1,
    status: "current",
    category: "Activities",
    noticeNumber: "PRM/2026/035",
    body: "A guest lecture on 'Applications of Machine Learning in Healthcare' will be held on 19 November 2026 at 2:00 PM in Room 301. The speaker is Dr. Anjali Mehta from IIT Bombay. Open to all students.",
    highlightedSentence:
      "guest lecture on 'Applications of Machine Learning in Healthcare' will be held on 19 November 2026",
  },
  {
    id: "n36",
    title: "Semester 4 Project Group Registration",
    issuer: "Exam Cell",
    date: "07 Nov 2026",
    page: 1,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/036",
    body: "All Semester 4 students must register their project groups by 28 November 2026. Each group should have 3 to 5 members. Individual projects require prior approval from the HOD.",
    highlightedSentence:
      "must register their project groups by 28 November 2026",
  },
  {
    id: "n37",
    title: "Bus Route Change — Route 7A",
    issuer: "Transport Office",
    date: "06 Nov 2026",
    page: 1,
    status: "current",
    category: "Transport",
    noticeNumber: "PRM/2026/037",
    body: "Due to road construction on MG Road, Bus Route 7A will be diverted via SV Road effective 10 November 2026. The morning pick-up time from Andheri station will change from 7:15 AM to 7:00 AM.",
    highlightedSentence:
      "Bus Route 7A will be diverted via SV Road effective 10 November 2026",
  },
  {
    id: "n38",
    title: "Canteen Price Revision",
    issuer: "Administration",
    date: "05 Nov 2026",
    page: 1,
    status: "current",
    category: "General",
    noticeNumber: "PRM/2026/038",
    body: "Canteen meal prices have been revised effective 15 November 2026. The standard thali is now Rs. 60 (previously Rs. 50). Subsidised rates for scholarship holders remain unchanged at Rs. 30.",
    highlightedSentence:
      "standard thali is now Rs. 60 (previously Rs. 50)",
  },
  {
    id: "n39",
    title: "Placement Drive — TCS & Infosys",
    issuer: "Placement Cell",
    date: "04 Nov 2026",
    page: 1,
    status: "current",
    category: "Placement",
    noticeNumber: "PRM/2026/039",
    body: "TCS and Infosys campus placement drives will be held on 1 December 2026 and 3 December 2026 respectively. Eligible students (Semester 5 and 6) must register on the placement portal by 20 November 2026.",
    highlightedSentence:
      "TCS and Infosys campus placement drives will be held on 1 December 2026 and 3 December 2026",
  },
  {
    id: "n40",
    title: "Wi-Fi Password Reset",
    issuer: "IT Department",
    date: "03 Nov 2026",
    page: 1,
    status: "current",
    category: "IT",
    noticeNumber: "PRM/2026/040",
    body: "The campus Wi-Fi password will be reset on 16 November 2026. Students must use their college email to re-authenticate. Contact the IT helpdesk (Room 102) for login issues.",
    highlightedSentence:
      "campus Wi-Fi password will be reset on 16 November 2026",
  },
  {
    id: "n41",
    title: "NSS Camp — Village Adoption Programme",
    issuer: "NSS Cell",
    date: "02 Nov 2026",
    page: 1,
    status: "current",
    category: "Activities",
    noticeNumber: "PRM/2026/041",
    body: "NSS volunteers are required to register for the 7-day village adoption camp from 10 December to 16 December 2026. Registration closes on 25 November 2026. All registered volunteers will receive attendance exemption for the camp period.",
    highlightedSentence:
      "7-day village adoption camp from 10 December to 16 December 2026",
  },
  {
    id: "n42",
    title: "Examination Hall Ticket Distribution",
    issuer: "Exam Cell",
    date: "01 Nov 2026",
    page: 1,
    status: "current",
    category: "Exams",
    noticeNumber: "PRM/2026/042",
    body: "Hall tickets for the Semester 4 end-of-semester examinations will be distributed from the department office between 1 December and 5 December 2026. Students must carry their ID cards to collect hall tickets.",
    highlightedSentence:
      "Hall tickets will be distributed from the department office between 1 December and 5 December 2026",
  },
];

// Facts are the approved answers the chatbot can use.
// factId -> fact data
export const seedFacts: Record<string, {
  factId: string;
  key: string;
  value: string;
  appliesTo: string;
  validUntil: string;
  replaces?: string;
  sources: { factId: string; notice: string; page: number }[];
  contact?: string;
  keywords: string[];
  scope: { course: CourseId; semester: Semester } | "all";
}> = {
  lateFee: {
    factId: "f-latefee",
    key: "late fee",
    value: "Rs. 50",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "20 Nov 2026",
    sources: [{ factId: "f-latefee", notice: "Notice 10 Nov", page: 1 }],
    keywords: ["fee", "late", "late fee", "penalty"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  examForm: {
    factId: "f-examform",
    key: "exam form",
    value: "25 November 2026",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "25 Nov 2026",
    sources: [{ factId: "f-examform", notice: "Notice 05 Nov", page: 1 }],
    keywords: ["exam form", "form", "submission", "last date"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  labExam: {
    factId: "f-labexam",
    key: "lab exam time",
    value: "DISPUTED",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "—",
    sources: [
      { factId: "f-labexam-a", notice: "Notice 08 Nov", page: 3 },
      { factId: "f-labexam-b", notice: "Notice 11 Nov", page: 1 },
    ],
    keywords: ["lab", "lab exam", "practical", "timing", "time"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  hostelFee: {
    factId: "f-hostel",
    key: "hostel fee",
    value: "Rs. 12,000 due 15 November 2026",
    appliesTo: "All courses, Sem 1–2",
    validUntil: "15 Nov 2026",
    sources: [{ factId: "f-hostel", notice: "Notice 03 Nov", page: 1 }],
    keywords: ["hostel", "hostel fee", "dorm", "accommodation"],
    scope: "all",
  },
  libraryFee: {
    factId: "f-library",
    key: "library membership fee",
    value: "Rs. 500 per year",
    appliesTo: "All courses",
    validUntil: "31 Oct 2026",
    sources: [{ factId: "f-library", notice: "Notice 06 Nov", page: 2 }],
    keywords: ["library", "library fee", "library membership", "membership"],
    scope: "all",
  },
  // =================== NEW CHATBOT FACTS ===================
  sportsDay: {
    factId: "f-sports",
    key: "sports day",
    value: "5 December 2026 — register by 25 November 2026 at Sports Office",
    appliesTo: "All courses",
    validUntil: "25 Nov 2026",
    sources: [{ factId: "f-sports", notice: "Notice 13 Nov", page: 1 }],
    contact: "Sports Office",
    keywords: ["sports", "sports day", "annual sports", "sports registration", "khel"],
    scope: "all",
  },
  internalMarks: {
    factId: "f-internal",
    key: "internal marks",
    value: "Available on student portal. Challenge deadline: 18 November 2026",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "18 Nov 2026",
    sources: [{ factId: "f-internal", notice: "Notice 13 Nov", page: 1 }],
    contact: "Exam Cell",
    keywords: ["internal", "internal marks", "assessment", "marks", "internal assessment", "challenge marks"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  winterBreak: {
    factId: "f-winter",
    key: "winter break",
    value: "22 December 2026 to 2 January 2027. Last working day: 21 December 2026",
    appliesTo: "All courses",
    validUntil: "02 Jan 2027",
    sources: [{ factId: "f-winter", notice: "Notice 12 Nov", page: 1 }],
    contact: "Principal's Office",
    keywords: ["winter", "break", "holiday", "vacation", "winter break", "christmas", "new year", "chutti"],
    scope: "all",
  },
  scholarship: {
    factId: "f-scholarship",
    key: "scholarship deadline",
    value: "National Merit Scholarship — submit with income certificates by 30 November 2026",
    appliesTo: "All courses",
    validUntil: "30 Nov 2026",
    sources: [{ factId: "f-scholarship", notice: "Notice 11 Nov", page: 1 }],
    contact: "Student Welfare Office",
    keywords: ["scholarship", "merit", "national merit", "income certificate", "scholarship deadline", "financial aid"],
    scope: "all",
  },
  projectGroup: {
    factId: "f-project",
    key: "project group",
    value: "Register by 28 November 2026. Group size: 3–5 members. Individual projects need HOD approval.",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "28 Nov 2026",
    sources: [{ factId: "f-project", notice: "Notice 07 Nov", page: 1 }],
    contact: "Department Office",
    keywords: ["project", "group", "project group", "project registration", "team", "group registration"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  hallTicket: {
    factId: "f-hallticket",
    key: "hall ticket",
    value: "Collect from department office between 1–5 December 2026. Carry ID card.",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "05 Dec 2026",
    sources: [{ factId: "f-hallticket", notice: "Notice 01 Nov", page: 1 }],
    contact: "Exam Cell",
    keywords: ["hall ticket", "admit card", "exam ticket", "hall", "ticket"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  busRoute: {
    factId: "f-bus",
    key: "bus route",
    value: "Route 7A diverted via SV Road from 10 Nov 2026. Andheri pick-up changed to 7:00 AM.",
    appliesTo: "All courses",
    validUntil: "31 Dec 2026",
    sources: [{ factId: "f-bus", notice: "Notice 06 Nov", page: 1 }],
    contact: "Transport Office",
    keywords: ["bus", "route", "transport", "bus route", "7a", "andheri", "sv road"],
    scope: "all",
  },
  canteenPrice: {
    factId: "f-canteen",
    key: "canteen price",
    value: "Standard thali: Rs. 60 (from 15 Nov 2026). Subsidised for scholarship holders: Rs. 30.",
    appliesTo: "All courses",
    validUntil: "31 Dec 2026",
    sources: [{ factId: "f-canteen", notice: "Notice 05 Nov", page: 1 }],
    contact: "Administration",
    keywords: ["canteen", "mess", "food", "thali", "canteen price", "meal", "lunch", "khana"],
    scope: "all",
  },
  placement: {
    factId: "f-placement",
    key: "placement drive",
    value: "TCS: 1 Dec 2026, Infosys: 3 Dec 2026. Register on placement portal by 20 November 2026.",
    appliesTo: "Sem 5–6",
    validUntil: "03 Dec 2026",
    sources: [{ factId: "f-placement", notice: "Notice 04 Nov", page: 1 }],
    contact: "Placement Cell",
    keywords: ["placement", "tcs", "infosys", "campus", "drive", "job", "placement drive", "naukri"],
    scope: "all",
  },
  wifi: {
    factId: "f-wifi",
    key: "wifi password",
    value: "Wi-Fi password reset on 16 November 2026. Re-authenticate using college email. Helpdesk: Room 102.",
    appliesTo: "All courses",
    validUntil: "31 Dec 2026",
    sources: [{ factId: "f-wifi", notice: "Notice 03 Nov", page: 1 }],
    contact: "IT Department (Room 102)",
    keywords: ["wifi", "wi-fi", "internet", "password", "login", "network"],
    scope: "all",
  },
  nss: {
    factId: "f-nss",
    key: "nss camp",
    value: "Village adoption camp 10–16 December 2026. Register by 25 November. Attendance exemption given.",
    appliesTo: "All courses",
    validUntil: "25 Nov 2026",
    sources: [{ factId: "f-nss", notice: "Notice 02 Nov", page: 1 }],
    contact: "NSS Cell",
    keywords: ["nss", "camp", "village", "volunteer", "nss camp", "national service"],
    scope: "all",
  },
  idCard: {
    factId: "f-idcard",
    key: "id card replacement",
    value: "Apply by 22 November 2026. Replacement fee: Rs. 200. Last batch this academic year.",
    appliesTo: "All courses",
    validUntil: "22 Nov 2026",
    sources: [{ factId: "f-idcard", notice: "Notice 09 Nov", page: 1 }],
    contact: "Administration",
    keywords: ["id card", "id", "identity card", "lost id", "replacement", "duplicate id"],
    scope: "all",
  },
  antiRagging: {
    factId: "f-antiragging",
    key: "anti-ragging session",
    value: "20 November 2026, 10:00 AM, Auditorium. Compulsory for all first-year students.",
    appliesTo: "Sem 1–2",
    validUntil: "20 Nov 2026",
    sources: [{ factId: "f-antiragging", notice: "Notice 10 Nov", page: 1 }],
    contact: "Dean of Students",
    keywords: ["ragging", "anti ragging", "anti-ragging", "session", "awareness"],
    scope: "all",
  },
  practicalReg: {
    factId: "f-practical",
    key: "practical registration",
    value: "Complete by 4 December 2026. Mandatory for all lab subjects.",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "04 Dec 2026",
    sources: [{ factId: "f-practical", notice: "Notice 09 Nov", page: 2 }],
    contact: "Exam Cell",
    keywords: ["practical", "practical registration", "lab registration", "register practical"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  feeWindow: {
    factId: "f-feewindow",
    key: "fee payment window",
    value: "Extended to 26 November 2026. Already paid? No action needed.",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "26 Nov 2026",
    sources: [{ factId: "f-feewindow", notice: "Notice 10 Nov", page: 1 }],
    contact: "Accounts Office",
    keywords: ["fee", "payment", "fee window", "fee deadline", "pay fee", "tuition", "fees kab tak"],
    scope: { course: "bsc-ds", semester: 4 },
  },
  guestLecture: {
    factId: "f-guestlecture",
    key: "guest lecture",
    value: "ML in Healthcare by Dr. Anjali Mehta (IIT Bombay), 19 Nov 2026, 2:00 PM, Room 301.",
    appliesTo: "All courses",
    validUntil: "19 Nov 2026",
    sources: [{ factId: "f-guestlecture", notice: "Notice 08 Nov", page: 1 }],
    contact: "Department of Data Science",
    keywords: ["guest lecture", "lecture", "machine learning", "healthcare", "ml", "seminar", "workshop"],
    scope: "all",
  },
  admission: {
    factId: "f-admission",
    key: "admission 2027",
    value: "Applications open 1 December 2026, close 15 January 2027. Online form only.",
    appliesTo: "All courses (2027-28 intake)",
    validUntil: "15 Jan 2027",
    sources: [{ factId: "f-admission", notice: "Notice 04 Nov", page: 1 }],
    contact: "Principal's Office",
    keywords: ["admission", "admission 2027", "apply", "application", "entrance", "new admission"],
    scope: "all",
  },
  timetable: {
    factId: "f-timetable",
    key: "revised timetable",
    value: "New timetable effective 16 November 2026. Check department noticeboard for lab schedule.",
    appliesTo: "B.Sc Data Science, Sem 4",
    validUntil: "31 Dec 2026",
    sources: [{ factId: "f-timetable", notice: "Notice 02 Nov", page: 1 }],
    contact: "Exam Cell",
    keywords: ["timetable", "schedule", "class schedule", "time table", "lecture timing"],
    scope: { course: "bsc-ds", semester: 4 },
  },
};

export const seedFactRows: FactRow[] = [
  {
    id: "fr1",
    factKey: "Late fee",
    value: "Rs. 75",
    oldValue: "Rs. 50",
    scope: { course: "bsc-ds", semester: 4 },
    replaces: "Notice 10 Nov",
    status: "pending",
    noticeId: "n12",
  },
  {
    id: "fr3",
    factKey: "Exam form deadline",
    value: "30 Nov 2026",
    oldValue: "25 Nov 2026",
    scope: { course: "bsc-ds", semester: 4 },
    replaces: "Notice 05 Nov",
    status: "pending",
    noticeId: "n25",
  },
  {
    id: "fr2",
    factKey: "Lab exam time",
    value: "2:00 PM – 5:00 PM",
    oldValue: "9:00 AM – 12:00 PM",
    scope: { course: "bsc-ds", semester: 4 },
    replaces: "Notice 08 Nov",
    status: "pending",
    conflict: "Conflict with notice #19",
    noticeId: "n19",
  },
  // =================== NEW PENDING FACT ROWS ===================
  {
    id: "fr4",
    factKey: "Fee payment window",
    value: "26 Nov 2026",
    oldValue: "20 Nov 2026",
    scope: { course: "bsc-ds", semester: 4 },
    replaces: "Notice 08 Nov",
    status: "pending",
    noticeId: "n21",
  },
  {
    id: "fr5",
    factKey: "Canteen thali price",
    value: "Rs. 60",
    oldValue: "Rs. 50",
    scope: { course: "bsc-ds", semester: 4 },
    status: "pending",
    noticeId: "n38",
  },
  {
    id: "fr6",
    factKey: "Bus Route 7A pick-up time",
    value: "7:00 AM (Andheri)",
    oldValue: "7:15 AM (Andheri)",
    scope: { course: "bsc-ds", semester: 4 },
    status: "pending",
    noticeId: "n37",
  },
  {
    id: "fr7",
    factKey: "Project group registration",
    value: "28 Nov 2026",
    scope: { course: "bsc-ds", semester: 4 },
    status: "pending",
    noticeId: "n36",
  },
];

export const seedUnanswered: UnansweredItem[] = [
  { id: "u1", question: "Re-exam date?", count: 14 },
  { id: "u2", question: "Hostel gate timing?", count: 6 },
  // =================== NEW UNANSWERED QUESTIONS ===================
  { id: "u3", question: "When will semester 4 results be declared?", count: 22 },
  { id: "u4", question: "Is there a make-up class for 10 Nov holiday?", count: 9 },
  { id: "u5", question: "How to apply for bonafide certificate?", count: 8 },
  { id: "u6", question: "What is the passing criteria for internals?", count: 7 },
  { id: "u7", question: "Can I change my elective subject?", count: 5 },
  { id: "u8", question: "Backlog exam registration last date?", count: 11 },
  { id: "u9", question: "Where to submit medical leave application?", count: 4 },
  { id: "u10", question: "Is there a grace marks policy?", count: 3 },
];

export const seedNoticesForReview = {
  title: "Revised Late Fee Circular — November 2026",
  issuer: "Accounts Office",
  date: "12 Nov 2026",
  page: 2,
  body: "Pursuant to the earlier circular dated 10 November 2026, the late fee has been revised to Rs. 75 for all late fee payments. This supersedes the previous circular. Applies to B.Sc Data Science Semester 4 students.",
  highlightedSentence:
    "the late fee has been revised to Rs. 75 for all late fee payments",
};
