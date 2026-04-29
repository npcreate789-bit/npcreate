import { TrendingUp, Target, Film, BarChart3 } from "lucide-react"

const services = [
  {
    icon: TrendingUp,
    title: "ยิงแอด GMV Max",
    description:
      "เพิ่มยอดขายด้วยระบบโฆษณา GMV Max ของ TikTok Shop ที่ออปติไมซ์ให้ได้ ROAS สูงสุด",
    highlight: "เฉลี่ย ROAS 8–15x",
  },
  {
    icon: Target,
    title: "วางกลยุทธ์ TikTok Shop",
    description:
      "วิเคราะห์คู่แข่ง หาโอกาส และวางแผนการตลาดแบบครบวงจร ตั้งแต่ pricing ถึง campaign",
    highlight: "แผนรายเดือน",
  },
  {
    icon: Film,
    title: "Content & Creative",
    description:
      "ผลิต creative สำหรับยิงแอด ทำ thumbnail ที่ดึงดูด และ optimize เนื้อหาให้ convert",
    highlight: "A/B Testing ทุก creative",
  },
  {
    icon: BarChart3,
    title: "รายงานผล & วิเคราะห์",
    description:
      "Dashboard รายสัปดาห์ วิเคราะห์ข้อมูลเชิงลึก และปรับ strategy แบบ real-time",
    highlight: "Weekly Report",
  },
]

export function ServicesSection() {
  return (
    <section className="py-24 bg-[#0F172A]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="text-center mb-14">
          <span className="text-[#6366F1] text-sm font-semibold uppercase tracking-widest">
            บริการของเรา
          </span>
          <h2 className="font-display font-bold text-3xl sm:text-4xl text-white mt-3">
            ครบทุกขั้นตอน ดูแลถึง Result
          </h2>
          <p className="text-slate-400 mt-4 max-w-xl mx-auto">
            ไม่ใช่แค่ยิงแอด — เราวางกลยุทธ์ ผลิต creative และติดตามผลลัพธ์จริงให้คุณ
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {services.map((service) => {
            const Icon = service.icon
            return (
              <div
                key={service.title}
                className="group bg-[#1E293B] hover:bg-[#1E293B]/80 border border-white/5 hover:border-[#6366F1]/30 rounded-2xl p-6 transition-all"
              >
                <div className="w-12 h-12 bg-[#6366F1]/10 rounded-xl flex items-center justify-center mb-5 group-hover:bg-[#6366F1]/20 transition-colors">
                  <Icon size={22} className="text-[#6366F1]" />
                </div>
                <h3 className="font-display font-semibold text-white text-lg mb-2">
                  {service.title}
                </h3>
                <p className="text-slate-400 text-sm leading-relaxed mb-4">
                  {service.description}
                </p>
                <span className="inline-block bg-[#F59E0B]/10 text-[#F59E0B] text-xs font-medium px-3 py-1 rounded-full">
                  {service.highlight}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
