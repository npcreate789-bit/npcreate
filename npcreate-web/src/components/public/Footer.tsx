import Link from "next/link"

const links = [
  { label: "ผลงาน", href: "/portfolio" },
  { label: "บริการ", href: "/services" },
  { label: "เกี่ยวกับเรา", href: "/about" },
  { label: "ติดต่อ", href: "/contact" },
]

export function Footer() {
  return (
    <footer className="bg-[#0A0F1E] border-t border-white/5">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-12">
        <div className="flex flex-col md:flex-row justify-between items-start gap-8">
          <div className="max-w-xs">
            <Link href="/" className="font-display font-bold text-xl text-white">
              NP<span className="text-[#6366F1]">Create</span>
            </Link>
            <p className="text-slate-400 text-sm mt-3 leading-relaxed">
              ปั้นยอดขาย TikTok Shop ของคุณให้โต 10 เท่า ด้วย GMV Max
            </p>
            <a
              href="https://lin.ee/XXXXXXX"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-[#06C755] hover:text-[#05a847] text-sm font-medium mt-4 transition-colors"
            >
              Line OA: @npcreate
            </a>
          </div>

          <nav className="flex flex-wrap gap-x-8 gap-y-3">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-slate-400 hover:text-white text-sm transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="border-t border-white/5 mt-10 pt-6 text-center text-slate-500 text-xs">
          © {new Date().getFullYear()} NP Create. All rights reserved.
        </div>
      </div>
    </footer>
  )
}
