import { HeroSection } from "@/components/public/HeroSection"
import { ServicesSection } from "@/components/public/ServicesSection"
import { WhyUsSection } from "@/components/public/WhyUsSection"
import { CTASection } from "@/components/public/CTASection"

export default function HomePage() {
  return (
    <main>
      <HeroSection />
      <ServicesSection />
      <WhyUsSection />
      <CTASection />
    </main>
  )
}
