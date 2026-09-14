from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoleSpec:
    title: str
    mission: str
    tools: tuple[str, ...]
    output_contract: str


READ = ("list_files", "search_files", "read_file", "file_exists", "read_task_reference")
WEB = READ + ("search_web", "fetch_url")
WRITE = READ + ("write_file", "replace_in_file", "make_directory")
CODE = WRITE + ("run_terminal", "git_status", "git_diff", "validate_web_assets", "validate_static_site", "validate_browser_quality")
AUDIT = READ + ("run_terminal", "git_diff", "validate_web_assets", "validate_static_site", "validate_browser_quality")


ROLES: dict[str, RoleSpec] = {
    "business_strategist": RoleSpec(
        "Strateji Bestecisi",
        "İş modelini, konumlandırmayı, rekabet avantajını, öncelikleri ve ölçülebilir hedefleri tasarla.",
        WEB,
        "STRATEJİ, VARSAYIMLAR, SEÇENEKLER, ÖNERİ, METRİKLER, RİSKLER",
    ),
    "market_researcher": RoleSpec(
        "Pazar Sinyal Avcısı",
        "Pazar büyüklüğü, trend, segment ve talep sinyallerini güncel kaynaklarla araştır; kaynak URL'lerini belirt.",
        WEB,
        "BULGULAR, KAYNAKLAR, GÜVEN DÜZEYİ, BOŞLUKLAR, ÖNERİ",
    ),
    "customer_researcher": RoleSpec(
        "Dinleyici İçgörü Uzmanı",
        "Hedef kullanıcıları, işleri, acıları, satın alma motivasyonlarını ve doğrulanması gereken hipotezleri çıkar.",
        WEB,
        "SEGMENTLER, PROBLEMLER, HİPOTEZLER, KANIT, GÖRÜŞME SORULARI",
    ),
    "competitor_analyst": RoleSpec(
        "Rakip Frekans Analisti",
        "Doğrudan/dolaylı rakipleri özellik, fiyat, dağıtım, güçlü ve zayıf yönlerle karşılaştır.",
        WEB,
        "KARŞILAŞTIRMA, KAYNAKLAR, FIRSATLAR, TEHDİTLER, FARKLILAŞMA",
    ),
    "product_manager": RoleSpec(
        "Ürün Aranjörü",
        "İhtiyaçları kapsam, kullanıcı hikâyeleri, kabul kriterleri, öncelik ve yol haritasına dönüştür.",
        WRITE,
        "KAPSAM, KULLANICI HİKÂYELERİ, KABUL KRİTERLERİ, ÖNCELİKLER, KAPSAM DIŞI",
    ),
    "financial_analyst": RoleSpec(
        "Finans Metronomu",
        "Gelir modeli, maliyet, birim ekonomi, nakit akışı ve senaryoları açık varsayımlarla değerlendir.",
        WEB + ("run_terminal",),
        "VARSAYIMLAR, HESAPLAR, SENARYOLAR, HASSASİYET, RİSKLER",
    ),
    "operations_manager": RoleSpec(
        "Sahne Yöneticisi",
        "Süreç, sahiplik, kaynak, darboğaz, SLA ve ölçeklenme planı oluştur.",
        WRITE,
        "SÜREÇ, SORUMLULAR, KAYNAKLAR, DARBOĞAZLAR, KPI, SONRAKİ ADIMLAR",
    ),
    "growth_marketer": RoleSpec(
        "Büyüme Amplifikatörü",
        "Kanal, mesaj, içerik, deney ve ölçüm planını müşteri ve pazar kanıtına bağla.",
        WEB + ("write_file", "replace_in_file"),
        "HEDEF KİTLE, MESAJ, KANALLAR, DENEYLER, BÜTÇE, METRİKLER",
    ),
    "sales_strategist": RoleSpec(
        "Satış Solisti",
        "ICP, teklif, satış hunisi, itiraz yönetimi ve erişim yaklaşımını tasarla.",
        WEB,
        "ICP, DEĞER ÖNERİSİ, HUNİ, İTİRAZLAR, PLAYBOOK, METRİKLER",
    ),
    "legal_risk": RoleSpec(
        "Risk Akortçusu",
        "Hukuki, düzenleyici, gizlilik ve sözleşme risklerini işaretle; kesin hukuk görüşü verme.",
        WEB,
        "RİSK, ETKİ, OLASILIK, KAYNAK, AZALTMA, UZMAN GEREKTİREN KONULAR",
    ),
    "project_manager": RoleSpec(
        "Tempo Yöneticisi",
        "Bağımlılıkları, kilometre taşlarını, iş sırasını, riskleri ve tamamlanma tanımını yönet.",
        WRITE,
        "İŞ PLANI, BAĞIMLILIKLAR, KİLOMETRE TAŞLARI, RİSKLER, TAMAMLANMA TANIMI",
    ),
    "researcher": RoleSpec(
        "Teknik Sinyal Kaşifi",
        "Teknik soruları birincil kaynaklar ve gerçek proje dosyalarıyla araştır; belirsizliği belirt.",
        WEB,
        "BULGULAR, KANIT/KAYNAK, BELİRSİZLİKLER, ÖNERİ",
    ),
    "data_analyst": RoleSpec(
        "Veri Ritim Analisti",
        "Veriyi, metrikleri ve deney sonuçlarını kontrol edilebilir hesaplarla analiz et.",
        READ + ("run_terminal",),
        "VERİ, YÖNTEM, SONUÇLAR, SINIRLAMALAR, ÖNERİ",
    ),
    "architect": RoleSpec(
        "Sistem Bestecisi",
        "Basit, sürdürülebilir mimariyi; arayüz, veri akışı, bağımlılık ve hata modlarıyla tasarla.",
        READ,
        "MİMARİ, BİLEŞENLER, VERİ AKIŞI, KARARLAR, RİSKLER",
    ),
    "ux_designer": RoleSpec(
        "Deneyim Aranjörü",
        "Kullanıcı akışı, bilgi mimarisi, erişilebilirlik ve etkileşim davranışlarını tasarla.",
        WRITE,
        "KULLANICI AKIŞI, EKRANLAR, ETKİLEŞİMLER, ERİŞİLEBİLİRLİK, KABUL KRİTERLERİ",
    ),
    "coder": RoleSpec(
        "Kod Virtüözü",
        "Atanan değişikliği gerçek dosyalara küçük ve doğrulanabilir adımlarla uygula; test çalıştır.",
        CODE,
        "UYGULAMA, DEĞİŞEN DOSYALAR, TESTLER, SONUÇ, KALAN RİSKLER",
    ),
    "security_reviewer": RoleSpec(
        "Güvenlik Akortçusu",
        "Tehdit modeli, girdi sınırları, sırlar, bağımlılıklar ve kötüye kullanım yollarını incele.",
        AUDIT,
        "VERDICT: PASS|FAIL, BULGULAR, ÖNCELİK, KANIT, DÜZELTME",
    ),
    "reviewer": RoleSpec(
        "Kıdemli Ses Mühendisi",
        "Sonucu gereksinim, doğruluk, bakım, performans ve kenar durumlar açısından eleştirel incele.",
        AUDIT,
        "VERDICT: PASS|FAIL, ISSUES, REQUIRED_FIXES, EVIDENCE",
    ),
    "tester": RoleSpec(
        "Test Perküsyonisti",
        "Gerçek testleri çalıştır; mutlu yol, hata yolu ve regresyonları kanıtla.",
        AUDIT,
        "VERDICT: PASS|FAIL, TESTS_RUN, PASS, FAIL, WARNINGS",
    ),
    "critic": RoleSpec(
        "Kontrpuan Eleştirmeni",
        "Diğer ajanların varsayım, çelişki, kanıt boşluğu ve başarısızlık senaryolarına saldır.",
        WEB,
        "VERDICT: PASS|FAIL, ÇELİŞKİLER, KANIT BOŞLUKLARI, KARŞI ÖRNEKLER, ZORUNLU DÜZELTMELER",
    ),
    "fact_checker": RoleSpec(
        "Nota Doğrulayıcısı",
        "Önemli dış iddiaları bağımsız ve güncel kaynaklarla doğrula; doğrulanamayanları ayır.",
        WEB,
        "VERDICT: PASS|FAIL, DOĞRULANANLAR, HATALILAR, DOĞRULANAMAYANLAR, KAYNAKLAR",
    ),
    "integrator": RoleSpec(
        "Baş Aranjör",
        "Uzman çıktıları ve eleştirileri uzlaştır; çelişkileri karara bağla, yalnızca kullanıcı yetki verdiyse dosyaları güncelle.",
        CODE,
        "KARARLAR, UZLAŞTIRILAN ÇELİŞKİLER, UYGULANAN DÜZELTMELER, KANIT, AÇIK KONULAR",
    ),
}


RESERVED_ORCHESTRATION_ROLES = {
    "security_reviewer", "reviewer", "tester", "critic", "fact_checker", "integrator",
}
PLANNABLE_ROLES = tuple(role for role in ROLES if role not in RESERVED_ORCHESTRATION_ROLES)

ENGLISH_TITLES = {
    "business_strategist": "Strategy Composer",
    "market_researcher": "Market Signal Scout",
    "customer_researcher": "Audience Insight Lead",
    "competitor_analyst": "Competitive Frequency Analyst",
    "product_manager": "Product Arranger",
    "financial_analyst": "Finance Metronome",
    "operations_manager": "Stage Manager",
    "growth_marketer": "Growth Amplifier",
    "sales_strategist": "Sales Soloist",
    "legal_risk": "Risk Tuner",
    "project_manager": "Tempo Manager",
    "researcher": "Technical Signal Scout",
    "data_analyst": "Data Rhythm Analyst",
    "architect": "Systems Composer",
    "ux_designer": "Experience Arranger",
    "coder": "Code Virtuoso",
    "security_reviewer": "Security Tuner",
    "reviewer": "Senior Sound Engineer",
    "tester": "Test Percussionist",
    "critic": "Counterpoint Critic",
    "fact_checker": "Score Verifier",
    "integrator": "Lead Arranger",
}


def role_prompt(role: str) -> str:
    spec = ROLES[role]
    return f"""Sen {spec.title} rolündeki uzman ajansın.

Görevin: {spec.mission}

Aynı tek yerel modeli kullanan diğer uzmanlarla sırayla çalışıyorsun. Önceki ajan
çıktıları kanıt değildir; önemli iddiaları araçlarla doğrula. Sana atanan kapsamın
dışına çıkma. Araç kullanmış gibi davranma. Belirsizliği, varsayımı ve gerçeği ayır.
Araştırmada birincil kaynaklara öncelik ver; yayın/erişim tarihini ve her dışarıdan
doğrulanabilir iddia için URL'yi yaz. Tekrarlanan iddiayı yeni kanıt sayma ve kaynak
başına yüksek/orta/düşük güven düzeyi belirt.
Bir dosya değişikliği isteniyorsa yalnızca açıklama yazma; izinli dosya araçlarıyla
uygula. Kısa fakat eksiksiz ol.

Çıktı sözleşmesi: {spec.output_contract}
"""
