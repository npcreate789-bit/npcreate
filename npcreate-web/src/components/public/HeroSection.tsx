import Link from "next/link"

export function HeroSection() {
  return (
    <section className="relative min-h-screen flex items-center justify-center bg-[#0F172A] overflow-hidden pt-16">
      <GradientOrbs />

      <div className="relative z-10 max-w-4xl mx-auto px-4 sm:px-6 text-center">
        <div className="inline-flex items-center gap-2 bg-[#6366F1]/10 border border-[#6366F1]/30 text-[#818CF8] text-sm font-medium px-4 py-1.5 rounded-full mb-8">
          <span className="w-2 h-2 bg-[#10B981] rounded-full animate-pulse" />
          รับลูกค้าใหม่ เดือน พ.ค. นี้ — เหลืออีก 3 สล็อต
        </div>

        <h1 className="font-display font-bold text-4xl sm:text-5xl lg:text-6xl text-white leading-tight mb-6">
          ปั้นยอดขาย TikTok Shop
          <br />
          <span className="text-[#6366F1]">ให้โต 10 เท่า</span>
          <br />
          ด้วย GMV Max
        </h1>

        <p className="text-slate-400 text-lg sm:text-xl max-w-2xl mx-auto mb-10 leading-relaxed">
          เราดูแลแบรนด์ TikTok Shop กว่า <span className="text-[#F59E0B] font-semibold">50+ แบรนด์</span>{" "}
          สร้างยอดขายรวม <span className="text-[#F59E0B] font-semibold">100+ ล้านบาท</span>{" "}
          ด้วยกลยุทธ์ GMV Max ที่พิสูจน์แล้ว
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <a
            href="https://lin.ee/XXXXXXX"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 bg-[#06C755] hover:bg-[#05a847] text-white font-semibold text-base px-8 py-3.5 rounded-xl transition-colors shadow-lg shadow-green-900/20"
          >
            ปรึกษาฟรีผ่าน Line OA
          </a>
          <Link
            href="/portfolio"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 border border-slate-600 hover:border-slate-400 text-slate-300 hover:text-white font-semibold text-base px-8 py-3.5 rounded-xl transition-colors"
          >
            ดูผลงานทั้งหมด
          </Link>
        </div>

        <div className="mt-16 grid grid-cols-3 gap-6 max-w-lg mx-auto">
          {[
            { value: "100M+", label: "GMV รวม (บาท)" },
            { value: "50+", label: "แบรนด์ที่ดูแล" },
            { value: "10x", label: "การเติบโตเฉลี่ย" },
          ].map((stat) => (
            <div key={stat.label} className="text-center">
              <div className="font-display font-bold text-2xl sm:text-3xl text-[#F59E0B]">
                {stat.value}
              </div>
              <div className="text-xs sm:text-sm text-slate-500 mt-1">{stat.label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function GradientOrbs() {
  return (
    <>
      <div className="absolute top-1/4 -left-32 w-96 h-96 bg-[#6366F1]/20 rounded-full blur-3xl" />
      <div className="absolute bottom-1/4 -right-32 w-96 h-96 bg-[#10B981]/15 rounded-full blur-3xl" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-[#6366F1]/5 rounded-full blur-3xl" />
    </>
  )
}
