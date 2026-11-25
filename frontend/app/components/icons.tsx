// Inline SVG icons on a 20px grid with a consistent 1.5px stroke. All are
// decorative (aria-hidden); the control that contains one carries the label.

import type { ReactNode } from "react";

function Icon({ children, size = 20, className }: { children: ReactNode; size?: number; className?: string }) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

type IconProps = { size?: number; className?: string };

export function TodayIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="3.25" />
      <path d="M10 2.75v1.5M10 15.75v1.5M2.75 10h1.5M15.75 10h1.5M4.9 4.9l1.06 1.06M14.04 14.04l1.06 1.06M4.9 15.1l1.06-1.06M14.04 5.96l1.06-1.06" />
    </Icon>
  );
}

export function CoursesIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.75 4.75c0-.55.45-1 1-1h3.5a1.75 1.75 0 0 1 1.75 1.75v10.75a1.5 1.5 0 0 0-1.5-1.5H4.75a1 1 0 0 1-1-1z" />
      <path d="M16.25 4.75c0-.55-.45-1-1-1h-3.5A1.75 1.75 0 0 0 10 5.5v10.75a1.5 1.5 0 0 1 1.5-1.5h3.75a1 1 0 0 0 1-1z" />
    </Icon>
  );
}

export function BellIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5.25 8.5a4.75 4.75 0 0 1 9.5 0c0 3.5 1.25 5 1.75 5.5H3.5c.5-.5 1.75-2 1.75-5.5z" />
      <path d="M8.25 16.5a1.85 1.85 0 0 0 3.5 0" />
    </Icon>
  );
}

export function SyncIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15.9 8.25A6 6 0 0 0 4.7 6.6M4.1 11.75a6 6 0 0 0 11.2 1.65" />
      <path d="M4.25 3.5v3.25H7.5M15.75 16.5v-3.25H12.5" />
    </Icon>
  );
}

export function ExternalIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8.5 4.75h-3a1 1 0 0 0-1 1v8.75a1 1 0 0 0 1 1h8.75a1 1 0 0 0 1-1v-3" />
      <path d="M11.25 4.75h4v4M15 5l-6 6" />
    </Icon>
  );
}

export function FileIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5.25 3.25h5.5l4 4v8.5a1 1 0 0 1-1 1h-8.5a1 1 0 0 1-1-1v-11.5a1 1 0 0 1 1-1z" />
      <path d="M10.5 3.5v4h4" />
    </Icon>
  );
}

export function LinkIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8.5 11.5l3-3" />
      <path d="M9.25 6.25l1.1-1.1a2.9 2.9 0 0 1 4.1 4.1l-1.1 1.1M10.75 13.75l-1.1 1.1a2.9 2.9 0 0 1-4.1-4.1l1.1-1.1" />
    </Icon>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 10.5l3.25 3.25L15 7" />
    </Icon>
  );
}

export function ChevronIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 5.5l4.5 4.5L8 14.5" />
    </Icon>
  );
}

export function ArrowLeftIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M15.5 10h-11M9 5.5L4.5 10 9 14.5" />
    </Icon>
  );
}

export function PinIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M7.5 3.5h5M8.5 3.5v4.25L5.75 11h8.5L11.5 7.75V3.5M10 11v5.5" />
    </Icon>
  );
}

export function WeightIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3.5 15.5h13M5.5 15.5v-4M8.5 15.5v-7M11.5 15.5v-9.5M14.5 15.5v-5.5" />
    </Icon>
  );
}

export function CalendarIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="3.5" y="4.5" width="13" height="12" rx="2" />
      <path d="M3.5 8.5h13M7 3v3M13 3v3" />
    </Icon>
  );
}

export function MegaphoneIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 8.25v3.5a1 1 0 0 0 1 1h1.5l6.5 3.5V3.75L6.5 7.25H5a1 1 0 0 0-1 1z" />
      <path d="M15.5 8a2.5 2.5 0 0 1 0 4M7 12.75l1 3.5" />
    </Icon>
  );
}

/** The app mark: an open notebook page with a margin rule and a tick. */
export function AppMark({ size = 22 }: { size?: number }) {
  return (
    <svg
      className="app-mark"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2" y="2" width="20" height="20" rx="6" fill="var(--accent)" />
      <path d="M7.5 8.5h9M7.5 12h4.5" stroke="var(--on-accent)" strokeWidth="1.6" strokeLinecap="round" opacity="0.6" />
      <path d="M12.75 14.75l1.75 1.75 3.25-3.5" fill="none" stroke="var(--on-accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
