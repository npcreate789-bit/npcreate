import { CheckCircle2 } from "lucide-react"

const reasons = [
  {
    title: "เชี่ยวชาญ GMV Max เท่านั้น",
    description: "เราโฟกัสเฉพาะ TikTok Shop GMV Max ไม่กระจายทำหลาย platform ความเชี่ยวชาญเฉพาะทางให้ผลลัพธ์ที่ดีกว่า",
  },
  {
    title: "ผลลัพธ์โปร่งใส ดูได้ Real-time",
    description: "ให้ access dashboard โฆษณาตรง ไม่มีปิดบัง ตัวเลข ROAS, GMV, ROAS ดูได้ทุกวัน",
  },
  {
    title: "ทีมที่รู้จริง ไม่ใช้ Freelance",
    description: "ทีมงานประจำที่มีประสบการณ์กับ TikTok Shop โดยตรง ไม่ outsource งานให้ freelance ที่ไม่มีประสบการณ์",
  },
  {
    title: "สัญญารายเดือน ไม่ผูกมัดยาว",
    description: "ไม่มีสัญญา 6–12 เดือน เริ่มได้เลยรายเดือน ถ้าไม่พอใจผลงาน หยุดได้ทันที",
  },
]

export function WhyUsSection() {
  return (
    <section className="py-24 bg-[#0A0F1E]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="grid lg:grid-cols-2 gap-14 items-center">
          <div>
            <span className="text-[#10B981] text-sm font-semibold uppercase tracking-widest">
              ทำไมต้องเลือก NP Create
            </span>
            <h2 className="font-display font-bold text-3xl sm:text-4xl text-white mt-3 mb-6">
              ผลงานพูดแทนทุกอย่าง
            </h2>
            <p className="text-slate-400 leading-relaxed">
              ตลาด TikTok Shop เติบโตเร็ว แต่การยิงแอดให้ได้ผลต้องอาศัยความเชี่ยวชาญเฉพาะ
              เราช่วยให้แบรนด์ของคุณได้เปรียบก่อนคู่แข่งจะตามทัน
            </p>

            <a
              href="https://lin.ee/XXXXXXX"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 bg-[#6366F1] hover:bg-[#4F46E5] text-white font-semibold px-6 py-3 rounded-xl mt-8 transition-colors"
            >
              คุยกับทีมงานเลย
            </a>
          </div>

          <div className="space-y-5">
            {reasons.map((reason) => (
              <div
                key={reason.title}
                className="flex gap-4 bg-[#1E293B]/50 border border-white/5 rounded-xl p-5"
              >
                <CheckCircle2 size={22} className="text-[#10B981] shrink-0 mt-0.5" />
                <div>
                  <h3 className="font-semibold text-white mb-1">{reason.title}</h3>
                  <p className="text-slate-400 text-sm leading-relaxed">{reason.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
