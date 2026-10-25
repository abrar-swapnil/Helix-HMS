export type Role = 'admin' | 'doctor' | 'patient' | 'receptionist';

export type DoctorStatus = 'available' | 'busy' | 'unavailable';
export type DoctorDepartment = 'general' | 'emergency';
export type RoomType = 'general' | 'emergency' | 'ot' | 'icu';
export type RoomStatus = 'available' | 'occupied';
export type AppointmentStatus = 'scheduled' | 'completed' | 'cancelled';
export type AppointmentType = 'general' | 'emergency';

export interface AuthUser {
  role: Role;
  username: string;
  name: string;
  id?: string;
  email?: string;
  phone?: string;
  doctorId?: string | null;
  patientId?: string | null;
  /** patients only: false until they have filled in their profile after signing up */
  profileComplete?: boolean;
}

export interface Doctor {
  id: string;
  code?: string;
  name: string;
  /** only sent to admin / receptionist / the doctor themself */
  email?: string;
  phone?: string;
  specialty: string;
  status: DoctorStatus;
  department: DoctorDepartment;
  waitingCount: number;
  patientsToday: number;
  estWaitMinutes: number;
  hasAccount?: boolean;
}

export interface Patient {
  id: string;
  code?: string;
  username: string;
  name: string;
  age: number | null;
  phone: string;
  gender: 'male' | 'female' | 'other';
  address: string;
  bloodType: string;
  previousDoctor?: string | null;
  documentCount?: number;
  profileComplete?: boolean;
  hasAccount?: boolean;
}

export interface Room {
  id: string;
  code?: string;
  number: string;
  type: RoomType;
  status: RoomStatus;
  patientId?: string | null;
  patientName?: string | null;
}

export interface Appointment {
  id: string;
  code?: string;
  patientId: string;
  patientName: string;
  patientPhone?: string;
  patientAge?: number | null;
  patientBloodType?: string;
  symptoms?: string;
  doctorId: string;
  doctorName: string;
  doctorSpecialty?: string;
  doctorUnavailable?: boolean;
  date: string;
  time: string;
  status: AppointmentStatus;
  type: AppointmentType;
  /** AI condition score 0-100 (how sick the patient is, from symptoms + age + medical history) */
  healthScore?: number;
  /** AI queue priority 0-100 = condition score + real-time waiting time */
  priorityScore?: number;
  waitingMinutes?: number;
  queuePosition?: number | null;
  arrivedAt?: string;
  reassignedFrom?: string | null;
  historyFlags?: string[];
  detected?: string[];
  cancelReason?: string | null;
}

export interface MedicalDoc {
  id: string;
  filename: string;
  contentType: string;
  size: number;
  notes: string;
  textExtracted: boolean;
  conditions: string[];
  uploadedAt: string;
}

export interface TriagePreview {
  healthScore: number;
  label: 'Critical' | 'Urgent' | 'Moderate' | 'Routine';
  detected: string[];
  historyFlags: string[];
  suggestedSpecialties: string[];
  availableSpecialties: string[];
  vitals: Record<string, number>;
  engine: string;
  estWaitMinutes: number | null;
}

export interface WeeklyStat {
  day: string;
  patients: number;
  appointments: number;
}

export interface AdminStats {
  doctors: number;
  availableDoctors: number;
  rooms: number;
  availableRooms: number;
  inpatients: number;
  todayAppointments: number;
  todayEmergency: number;
  weekly: (WeeklyStat & { date: string })[];
  specialtyCounts: Record<string, number>;
}

export interface DoctorStats {
  seenToday: number;
  waitingNow: number;
  thisWeek: number;
  weekly: { day: string; patients: number }[];
  recent: { name: string; age: number | null; lastVisit: string }[];
}

export interface Meta {
  today: string;
  now: string;
  timezone: string;
  specialties: string[];
  slotMinutes: number;
  dayStart: string;
  dayEnd: string;
  hospital: { name: string; phone: string; ambulance: string; email: string; website: string; emergency: string };
}

export interface ChatMessage {
  id: string;
  from: 'bot' | 'user';
  text: string;
  timestamp: Date;
}
