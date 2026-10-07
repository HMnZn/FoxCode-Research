import type { SVGProps } from 'react'

const paths = {
  workspace: 'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z',
  memory: 'M5 5h14v14H5z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3 M9 9h6v6H9z',
  spark: 'm12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z',
  settings: 'M4 7h16 M4 17h16 M8 4v6 M16 14v6',
  plus: 'M12 5v14 M5 12h14',
  arrow: 'M5 12h14 m-6-6 6 6-6 6',
  folder: 'M3 7V5h6l2 2h10v13H3z',
  code: 'm8 7-5 5 5 5 m8-10 5 5-5 5 M14 4l-4 16',
  terminal: 'm5 7 5 5-5 5 M13 17h6',
  check: 'm5 12 4 4L19 6',
  close: 'm6 6 12 12 M6 18 18 6',
  stop: 'M6 6h12v12H6z',
  chevron: 'm9 5 7 7-7 7',
  book: 'M4 3h13a3 3 0 0 1 3 3v15H7a3 3 0 0 1-3-3z M4 17h16 M8 7h8 M8 11h6',
  retry: 'M20 7v5h-5 M20 12a8 8 0 1 0-2 6',
  alert: 'M12 8v5 M12 17h.01 M12 3 2 21h20z',
} as const

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: keyof typeof paths }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    <path d={paths[name]} />
  </svg>
}

export function FoxMark({ className = '' }: { className?: string }) {
  return <svg className={className} width="32" height="32" viewBox="0 0 40 40" fill="none" aria-hidden="true">
    <path d="M5 7 15 12h10L35 7l-2 18-13 10L7 25Z" fill="currentColor" />
    <path d="m8 18 12 8 12-8-6 12H14Z" fill="white" opacity=".94" />
    <path d="m16 25 4 4 4-4Z" fill="currentColor" />
    <path d="m12 16 4 2m12-2-4 2" stroke="white" strokeWidth="2" strokeLinecap="round" />
  </svg>
}
