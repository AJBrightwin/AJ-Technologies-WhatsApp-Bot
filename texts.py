"""
Everything the bot says, in English, Tamil and Tanglish (Tamil in English letters).

Any other language (Hindi, Malayalam, Telugu, Hinglish ...) is translated from the
English text by the AI and remembered, so the customer always gets their own language.

To change a reply, edit the text here. Keep {name}-style placeholders as they are.
"""
import logging
import string

log = logging.getLogger('bot.texts')

BUILTIN = ('en', 'ta', 'tanglish')

LANG_NAMES = {
    'en': 'English', 'ta': 'Tamil', 'tanglish': 'Tanglish (Tamil written in English letters)',
    'hi': 'Hindi', 'hinglish': 'Hinglish (Hindi written in English letters)', 'ml': 'Malayalam',
    'te': 'Telugu', 'kn': 'Kannada', 'bn': 'Bengali', 'mr': 'Marathi', 'gu': 'Gujarati', 'pa': 'Punjabi',
    'or': 'Odia', 'ur': 'Urdu', 'ar': 'Arabic', 'fr': 'French', 'de': 'German', 'es': 'Spanish',
    'si': 'Sinhala', 'ms': 'Malay', 'id': 'Indonesian', 'zh': 'Chinese',
}

T = {
    # ------------------------------------------------------------------ menu
    'welcome': {
        'en': "Hi {name}! 👋 I'm *AJ Technologies Assistant*.\nWe build websites, online stores, apps and digital marketing for businesses across India.\n\nHow can I help you today?",
        'ta': "வணக்கம் {name}! 👋 நான் *AJ Technologies Assistant*.\nஇந்தியா முழுவதும் உள்ள வணிகங்களுக்கு இணையதளங்கள், ஆன்லைன் ஸ்டோர்கள், ஆப்ஸ் மற்றும் டிஜிட்டல் மார்க்கெட்டிங் செய்து தருகிறோம்.\n\nஇன்று நான் உங்களுக்கு எப்படி உதவலாம்?",
        'tanglish': "Vanakkam {name}! 👋 Naan *AJ Technologies Assistant*.\nIndia muzhuvadhum ulla businesses-ku websites, online stores, apps matrum digital marketing pannitharom.\n\nIndru ungalukku eppadi help pannalam?",
    },
    'menu_body': {
        'en': "Choose an option below, or just type your question. 😊",
        'ta': "கீழே ஒன்றைத் தேர்ந்தெடுங்கள், அல்லது உங்கள் கேள்வியை டைப் செய்யுங்கள். 😊",
        'tanglish': "Keezhe oru option-ah choose pannunga, illa unga question-ah type pannunga. 😊",
    },
    'menu_button': {'en': "Open menu", 'ta': "மெனு", 'tanglish': "Menu open"},
    'menu_section': {'en': "How can we help?", 'ta': "எப்படி உதவலாம்?", 'tanglish': "Eppadi help pannalam?"},
    'm_services': {'en': "🛠️ Our services", 'ta': "🛠️ எங்கள் சேவைகள்", 'tanglish': "🛠️ Engal services"},
    'm_services_d': {'en': "Websites, online stores, apps, marketing", 'ta': "இணையதளம், ஆன்லைன் ஸ்டோர், ஆப்ஸ், மார்க்கெட்டிங்", 'tanglish': "Website, online store, apps, marketing"},
    'm_prices': {'en': "💰 Prices", 'ta': "💰 விலை", 'tanglish': "💰 Price"},
    'm_prices_d': {'en': "How our pricing works", 'ta': "எங்கள் விலை எப்படி முடிவாகிறது", 'tanglish': "Engal price eppadi decide aagudhu"},
    'm_work': {'en': "📂 Our work", 'ta': "📂 எங்கள் படைப்புகள்", 'tanglish': "📂 Engal work"},
    'm_work_d': {'en': "Projects we have built", 'ta': "நாங்கள் உருவாக்கிய திட்டங்கள்", 'tanglish': "Naanga build panna projects"},
    'm_quote': {'en': "💬 Get a free quote", 'ta': "💬 இலவச மதிப்பீடு", 'tanglish': "💬 Free quote"},
    'm_quote_d': {'en': "Tell us what you need, we reply in 24 hours", 'ta': "உங்கள் தேவையைச் சொல்லுங்கள், 24 மணி நேரத்தில் பதில்", 'tanglish': "Unga requirement sollunga, 24 hours-la reply"},
    'm_call': {'en': "📅 Book a call", 'ta': "📅 அழைப்பு பதிவு", 'tanglish': "📅 Call book"},
    'm_call_d': {'en': "Pick a time for a free call", 'ta': "இலவச அழைப்புக்கு நேரம் தேர்வு செய்யுங்கள்", 'tanglish': "Free call-ku time choose pannunga"},
    'm_team': {'en': "👤 Talk to our team", 'ta': "👤 எங்கள் குழுவிடம் பேச", 'tanglish': "👤 Team kitta pesa"},
    'm_team_d': {'en': "We contact you within 24 hours", 'ta': "24 மணி நேரத்தில் தொடர்புகொள்வோம்", 'tanglish': "24 hours-la contact pannuvom"},
    'm_review': {'en': "⭐ Leave a review", 'ta': "⭐ விமர்சனம் எழுத", 'tanglish': "⭐ Review ezhudha"},
    'm_review_d': {'en': "For our clients", 'ta': "எங்கள் வாடிக்கையாளர்களுக்கு", 'tanglish': "Engal clients-ku"},
    'm_lang': {'en': "🌐 Language", 'ta': "🌐 மொழி", 'tanglish': "🌐 Language"},
    'm_lang_d': {'en': "English, தமிழ், Tanglish and more", 'ta': "English, தமிழ், Tanglish மற்றும் பல", 'tanglish': "English, தமிழ், Tanglish and more"},

    # ------------------------------------------------------------------ buttons
    'b_menu': {'en': "🏠 Menu", 'ta': "🏠 மெனு", 'tanglish': "🏠 Menu"},
    'b_quote': {'en': "💬 Get a quote", 'ta': "💬 மதிப்பீடு பெற", 'tanglish': "💬 Quote venum"},
    'b_work': {'en': "📂 Our work", 'ta': "📂 படைப்புகள்", 'tanglish': "📂 Engal work"},
    'b_call': {'en': "📅 Book a call", 'ta': "📅 அழைப்பு பதிவு", 'tanglish': "📅 Call book"},
    'b_skip': {'en': "Skip", 'ta': "தவிர்", 'tanglish': "Skip"},
    'b_yes': {'en': "✅ Yes", 'ta': "✅ ஆம்", 'tanglish': "✅ Aamam"},
    'b_more_svc': {'en': "🛠️ Other services", 'ta': "🛠️ மற்ற சேவைகள்", 'tanglish': "🛠️ Vera services"},

    # ------------------------------------------------------------------ general
    'error': {
        'en': "Sorry, something went wrong on our side. Please try again in a minute. 🙏",
        'ta': "மன்னிக்கவும், எங்கள் பக்கம் ஒரு சிக்கல் ஏற்பட்டது. ஒரு நிமிடம் கழித்து மீண்டும் முயலுங்கள். 🙏",
        'tanglish': "Sorry, engal side-la oru problem vandhuduchu. Oru nimisham kazhichu thirumba try pannunga. 🙏",
    },
    'didnt_get': {
        'en': "Sorry, I didn't quite get that. You can choose an option from the menu or type your question. 🙂",
        'ta': "மன்னிக்கவும், எனக்குச் சரியாகப் புரியவில்லை. மெனுவில் ஒன்றைத் தேர்ந்தெடுங்கள் அல்லது உங்கள் கேள்வியை டைப் செய்யுங்கள். 🙂",
        'tanglish': "Sorry, enakku sariya puriyala. Menu-la oru option choose pannunga illa unga question-ah type pannunga. 🙂",
    },
    'prices': {
        'en': "Every project is custom built, so the price depends on what you need (pages, features, online payments, app or marketing). 💡\n\nShare a few details and our team will send you a *free, clear quote within 24 hours* — no hidden costs.",
        'ta': "ஒவ்வொரு திட்டமும் உங்கள் தேவைக்கு ஏற்ப உருவாக்கப்படுகிறது, அதனால் விலை உங்கள் தேவையைப் பொறுத்தது (பக்கங்கள், வசதிகள், ஆன்லைன் பணம் செலுத்துதல், ஆப் அல்லது மார்க்கெட்டிங்). 💡\n\nசில விவரங்களைப் பகிருங்கள், எங்கள் குழு *24 மணி நேரத்தில் இலவச, தெளிவான மதிப்பீட்டை* அனுப்பும் — மறைமுகக் கட்டணம் இல்லை.",
        'tanglish': "Ovvoru project-um unga requirement-ku yetha maadhiri custom-ah build pannuvom, adhanaala price unga need-ah poruthu (pages, features, online payment, app illa marketing). 💡\n\nKonjam details share pannunga, engal team *24 hours-la free, clear quote* anuppuvanga — hidden charges illa.",
    },
    'human': {
        'en': "Thank you! 🙏 Our team will contact you *within 24 hours* on this number.\nMeanwhile, I'm right here — feel free to ask me anything.",
        'ta': "நன்றி! 🙏 எங்கள் குழு இந்த எண்ணில் *24 மணி நேரத்திற்குள்* உங்களைத் தொடர்புகொள்ளும்.\nஅதுவரை நான் இங்கேயே இருக்கிறேன் — எதுவும் கேளுங்கள்.",
        'tanglish': "Nandri! 🙏 Engal team indha number-la *24 hours-kulla* ungala contact pannuvanga.\nAdhu varaikkum naan inga dhaan irukken — edhu venumnaalum kelunga.",
    },
    'human_again': {
        'en': "Our team already has your request and will contact you within 24 hours. 🙏 Meanwhile, ask me anything.",
        'ta': "உங்கள் கோரிக்கை ஏற்கனவே எங்கள் குழுவிடம் உள்ளது, 24 மணி நேரத்திற்குள் தொடர்புகொள்வார்கள். 🙏 அதுவரை எதுவும் கேளுங்கள்.",
        'tanglish': "Unga request already engal team kitta irukku, 24 hours-kulla contact pannuvanga. 🙏 Adhu varaikkum edhu venumnaalum kelunga.",
    },
    'cancelled': {
        'en': "No problem, I've stopped that. If you need anything, just type here or tap Menu. 🙂",
        'ta': "சரி, அதை நிறுத்திவிட்டேன். ஏதாவது தேவைப்பட்டால் இங்கே டைப் செய்யுங்கள் அல்லது மெனுவைத் தட்டுங்கள். 🙂",
        'tanglish': "Seri, adha stop pannitten. Edhaavadhu venumna inga type pannunga illa Menu tap pannunga. 🙂",
    },
    'expired': {
        'en': "That option is no longer active. Here is the menu again. 👇",
        'ta': "அந்த விருப்பம் இப்போது செயலில் இல்லை. மெனு மீண்டும் இதோ. 👇",
        'tanglish': "Andha option ippo active illa. Menu thirumba idho. 👇",
    },

    # ------------------------------------------------------------------ services
    'svc_intro': {
        'en': "We build everything your business needs, end to end. Tap a service to know more. 👇",
        'ta': "உங்கள் வணிகத்திற்குத் தேவையான அனைத்தையும் தொடக்கம் முதல் முடிவு வரை செய்து தருகிறோம். மேலும் அறிய ஒரு சேவையைத் தட்டுங்கள். 👇",
        'tanglish': "Unga business-ku thevaiyaana ellathaiyum start to end pannitharom. Detail-ah theriya oru service-ah tap pannunga. 👇",
    },
    'svc_button': {'en': "View services", 'ta': "சேவைகள்", 'tanglish': "Services paaru"},
    'svc_all_include': {
        'en': "Every project includes a free consultation, design approval before coding, testing on every device, training and support after launch.",
        'ta': "ஒவ்வொரு திட்டத்திலும் இலவச ஆலோசனை, கோடிங்கிற்கு முன் வடிவமைப்பு ஒப்புதல், அனைத்து சாதனங்களிலும் சோதனை, பயிற்சி மற்றும் வெளியீட்டுக்குப் பின் ஆதரவு உண்டு.",
        'tanglish': "Ovvoru project-layum free consultation, coding-ku munnadi design approval, ella device-layum testing, training matrum launch-ku apram support irukku.",
    },
    'svc_web': {'en': "Business Websites", 'ta': "வணிக இணையதளங்கள்", 'tanglish': "Business Websites"},
    'svc_web_d': {'en': "Websites that build trust and bring enquiries", 'ta': "நம்பிக்கையும் விசாரணைகளும் தரும் இணையதளங்கள்", 'tanglish': "Trust-um enquiries-um kondu varum websites"},
    'svc_web_x': {
        'en': "*Business Websites* 🌐\nProfessional websites that build trust and bring in enquiries — for shops, clinics, restaurants, schools and professionals.\n\n*Included:* mobile-friendly design, contact form, WhatsApp button, Google Maps, SEO basics, English & Tamil, easy admin panel, SSL security, speed optimisation and free support after launch.",
        'ta': "*வணிக இணையதளங்கள்* 🌐\nகடைகள், மருத்துவமனைகள், உணவகங்கள், பள்ளிகள் மற்றும் தொழில் வல்லுநர்களுக்கு — நம்பிக்கையை உருவாக்கி விசாரணைகளைக் கொண்டுவரும் தொழில்முறை இணையதளங்கள்.\n\n*உள்ளடக்கம்:* மொபைலுக்கு ஏற்ற வடிவமைப்பு, தொடர்பு படிவம், வாட்ஸ்அப் பட்டன், Google Maps, அடிப்படை SEO, English & தமிழ், எளிய admin panel, SSL பாதுகாப்பு, வேகம் மற்றும் வெளியீட்டுக்குப் பின் இலவச ஆதரவு.",
        'tanglish': "*Business Websites* 🌐\nShops, clinics, restaurants, schools, professionals-ku — trust build panni enquiries kondu varum professional websites.\n\n*Included:* mobile-friendly design, contact form, WhatsApp button, Google Maps, SEO basics, English & Tamil, easy admin panel, SSL security, fast speed matrum launch-ku apram free support.",
    },
    'svc_shop': {'en': "E-commerce Stores", 'ta': "ஆன்லைன் ஸ்டோர்கள்", 'tanglish': "Online Stores"},
    'svc_shop_d': {'en': "Sell online with Razorpay payments", 'ta': "Razorpay மூலம் ஆன்லைனில் விற்பனை", 'tanglish': "Razorpay payment-oda online-la sell pannunga"},
    'svc_shop_x': {
        'en': "*E-commerce Stores* 🛒\nSell online with Razorpay payments (UPI, cards, net banking and wallets), product listings and order management.\n\nYou get an easy admin panel to add products, change prices and manage orders yourself.",
        'ta': "*ஆன்லைன் ஸ்டோர்கள்* 🛒\nRazorpay மூலம் பணம் பெறுதல் (UPI, கார்டு, நெட் பேங்கிங், வாலெட்), பொருட்கள் பட்டியல் மற்றும் ஆர்டர் நிர்வாகத்துடன் ஆன்லைனில் விற்பனை செய்யுங்கள்.\n\nபொருட்களைச் சேர்க்க, விலையை மாற்ற, ஆர்டர்களை நிர்வகிக்க எளிய admin panel கிடைக்கும்.",
        'tanglish': "*Online Stores* 🛒\nRazorpay payments (UPI, cards, net banking, wallets), product listing matrum order management-oda online-la sell pannunga.\n\nProducts add panna, price maatha, orders manage panna easy admin panel kudupom.",
    },
    'svc_landing': {'en': "Landing Pages", 'ta': "லேண்டிங் பக்கங்கள்", 'tanglish': "Landing Pages"},
    'svc_landing_d': {'en': "Single pages for campaigns and ads", 'ta': "விளம்பரங்களுக்கான ஒற்றைப் பக்கங்கள்", 'tanglish': "Ads, campaigns-ku single page"},
    'svc_landing_x': {
        'en': "*Landing Pages* 🎯\nFocused single pages for campaigns, launches and ads — built to turn visitors into enquiries.",
        'ta': "*லேண்டிங் பக்கங்கள்* 🎯\nவிளம்பரங்கள், அறிமுகங்கள் மற்றும் பிரச்சாரங்களுக்கான ஒற்றைப் பக்கங்கள் — பார்வையாளர்களை விசாரணைகளாக மாற்ற உருவாக்கப்பட்டவை.",
        'tanglish': "*Landing Pages* 🎯\nCampaigns, launches matrum ads-ku focused single pages — visitors-ah enquiries-ah maatha build pannadhu.",
    },
    'svc_redesign': {'en': "Website Redesign", 'ta': "இணையதள மறுவடிவமைப்பு", 'tanglish': "Website Redesign"},
    'svc_redesign_d': {'en': "Make your old website modern and fast", 'ta': "பழைய இணையதளத்தை நவீனமாக, வேகமாக மாற்ற", 'tanglish': "Pazhaya website-ah modern, fast-ah maatha"},
    'svc_redesign_x': {
        'en': "*Website Redesign* ✨\nGive your old website a modern, faster, mobile-friendly makeover — without losing your content.",
        'ta': "*இணையதள மறுவடிவமைப்பு* ✨\nஉங்கள் பழைய இணையதளத்தை உள்ளடக்கம் இழக்காமல் நவீனமான, வேகமான, மொபைலுக்கு ஏற்றதாக மாற்றுகிறோம்.",
        'tanglish': "*Website Redesign* ✨\nUnga pazhaya website-ah content edhuvum miss aagaama modern, fast, mobile-friendly-ah maathi tharom.",
    },
    'svc_saas': {'en': "Web Apps & SaaS", 'ta': "வெப் ஆப்ஸ் & SaaS", 'tanglish': "Web Apps & SaaS"},
    'svc_saas_d': {'en': "Online tools your team or customers log in to", 'ta': "லாகின் செய்து பயன்படுத்தும் ஆன்லைன் கருவிகள்", 'tanglish': "Login panni use panra online tools"},
    'svc_saas_x': {
        'en': "*Web Apps & SaaS* 💻\nOnline tools and platforms your customers or team can log in to — bookings, billing, dashboards, portals and more. Secure logins and an admin dashboard are included.",
        'ta': "*வெப் ஆப்ஸ் & SaaS* 💻\nஉங்கள் வாடிக்கையாளர்கள் அல்லது குழு லாகின் செய்து பயன்படுத்தும் ஆன்லைன் கருவிகள் — முன்பதிவு, பில்லிங், டாஷ்போர்டு, போர்டல் மற்றும் பல. பாதுகாப்பான லாகின் மற்றும் admin dashboard உண்டு.",
        'tanglish': "*Web Apps & SaaS* 💻\nUnga customers illa team login panni use panra online tools — bookings, billing, dashboards, portals and more. Secure login matrum admin dashboard irukku.",
    },
    'svc_app': {'en': "Mobile Apps", 'ta': "மொபைல் ஆப்ஸ்", 'tanglish': "Mobile Apps"},
    'svc_app_d': {'en': "Android & iOS apps, published for you", 'ta': "Android & iOS ஆப்ஸ், வெளியீடு உட்பட", 'tanglish': "Android & iOS apps, publish-um naanga"},
    'svc_app_x': {
        'en': "*Mobile Apps* 📱\nAndroid and iOS apps that put your business in every pocket. Tested on real devices and published on the Play Store and App Store for you.",
        'ta': "*மொபைல் ஆப்ஸ்* 📱\nஉங்கள் வணிகத்தை ஒவ்வொருவரின் கையிலும் கொண்டுசேர்க்கும் Android மற்றும் iOS ஆப்ஸ். உண்மையான சாதனங்களில் சோதித்து, Play Store மற்றும் App Store-இல் நாங்களே வெளியிடுவோம்.",
        'tanglish': "*Mobile Apps* 📱\nUnga business-ah ellaroda pocket-kum kondu pora Android & iOS apps. Real devices-la test panni Play Store, App Store-la naangale publish pannuvom.",
    },
    'svc_mkt': {'en': "Marketing & SEO", 'ta': "மார்க்கெட்டிங் & SEO", 'tanglish': "Marketing & SEO"},
    'svc_mkt_d': {'en': "Google, Maps, Instagram, Facebook, YouTube", 'ta': "Google, Maps, Instagram, Facebook, YouTube", 'tanglish': "Google, Maps, Instagram, Facebook, YouTube"},
    'svc_mkt_x': {
        'en': "*Digital Marketing & SEO* 📈\nShow up where your customers already are: SEO, Google Business Profile (Google Maps), and Instagram, Facebook & YouTube marketing.\n\nChoose a one-time setup or a monthly plan where we keep improving your visibility.",
        'ta': "*டிஜிட்டல் மார்க்கெட்டிங் & SEO* 📈\nஉங்கள் வாடிக்கையாளர்கள் இருக்கும் இடத்தில் நீங்கள் தெரிய: SEO, Google Business Profile (Google Maps), Instagram, Facebook & YouTube மார்க்கெட்டிங்.\n\nஒருமுறை அமைப்பு அல்லது மாதாந்திர திட்டம் — உங்கள் விருப்பம்.",
        'tanglish': "*Digital Marketing & SEO* 📈\nUnga customers irukura idathula neenga theriyanum: SEO, Google Business Profile (Google Maps), Instagram, Facebook & YouTube marketing.\n\nOne-time setup illa monthly plan — unga choice.",
    },
    'svc_wa': {'en': "WhatsApp Business", 'ta': "வாட்ஸ்அப் பிசினஸ்", 'tanglish': "WhatsApp Business"},
    'svc_wa_d': {'en': "Chat buttons, catalogues, auto replies", 'ta': "சாட் பட்டன், கேட்டலாக், தானியங்கி பதில்", 'tanglish': "Chat button, catalogue, auto reply"},
    'svc_wa_x': {
        'en': "*WhatsApp Business* 💬\nChat buttons, catalogues and automated replies for your customers — just like this assistant you're talking to now!",
        'ta': "*வாட்ஸ்அப் பிசினஸ்* 💬\nஉங்கள் வாடிக்கையாளர்களுக்கு சாட் பட்டன், கேட்டலாக் மற்றும் தானியங்கி பதில்கள் — நீங்கள் இப்போது பேசும் இந்த assistant போலவே!",
        'tanglish': "*WhatsApp Business* 💬\nUnga customers-ku chat buttons, catalogues matrum automatic replies — neenga ippo pesura indha assistant maadhiriye!",
    },
    'svc_care': {'en': "Domain, Hosting & AMC", 'ta': "டொமைன், ஹோஸ்டிங் & AMC", 'tanglish': "Domain, Hosting & AMC"},
    'svc_care_d': {'en': "Setup, updates, backups and renewals", 'ta': "அமைப்பு, அப்டேட், பேக்கப், புதுப்பித்தல்", 'tanglish': "Setup, updates, backups, renewals"},
    'svc_care_x': {
        'en': "*Domain, Hosting & AMC* 🛡️\nWe set up your domain and secure hosting with SSL, and look after everything under an annual maintenance plan: updates, backups, security checks, content changes and renewals.",
        'ta': "*டொமைன், ஹோஸ்டிங் & AMC* 🛡️\nடொமைன் மற்றும் SSL உடன் பாதுகாப்பான ஹோஸ்டிங்கை அமைத்து, ஆண்டு பராமரிப்புத் திட்டத்தில் அனைத்தையும் கவனித்துக்கொள்கிறோம்: அப்டேட், பேக்கப், பாதுகாப்புச் சோதனை, உள்ளடக்க மாற்றம் மற்றும் புதுப்பித்தல்.",
        'tanglish': "*Domain, Hosting & AMC* 🛡️\nDomain matrum SSL-oda secure hosting setup panni, annual maintenance plan-la ellathaiyum paathukkuvom: updates, backups, security checks, content changes, renewals.",
    },
    'svc_other': {'en': "Something else", 'ta': "வேறு ஏதாவது", 'tanglish': "Vera edhaavadhu"},

    # ------------------------------------------------------------------ enquiry
    'enq_start': {
        'en': "Great! Let me take a few details so our team can send you a *free quote*. It takes about a minute. 📝\n(Type *cancel* anytime to stop.)",
        'ta': "அருமை! எங்கள் குழு உங்களுக்கு *இலவச மதிப்பீடு* அனுப்ப சில விவரங்களைப் பெறுகிறேன். ஒரு நிமிடம் ஆகும். 📝\n(நிறுத்த எப்போது வேண்டுமானாலும் *cancel* என டைப் செய்யுங்கள்.)",
        'tanglish': "Super! Engal team ungalukku *free quote* anuppa konjam details vaangikiren. Oru nimisham dhaan aagum. 📝\n(Stop panna eppo venumnaalum *cancel* nu type pannunga.)",
    },
    'ask_name': {
        'en': "May I know your name?",
        'ta': "உங்கள் பெயரைத் தெரிந்துகொள்ளலாமா?",
        'tanglish': "Unga peyar enna?",
    },
    'ask_name_profile': {
        'en': "May I know your name? Tap the button if this is right, or type your name.",
        'ta': "உங்கள் பெயர் என்ன? இது சரி என்றால் பட்டனைத் தட்டுங்கள், இல்லையெனில் உங்கள் பெயரை டைப் செய்யுங்கள்.",
        'tanglish': "Unga peyar enna? Idhu sariyaa irundha button tap pannunga, illana unga peyar type pannunga.",
    },
    'bad_name': {
        'en': "Please type your name (just the name is enough). 🙂",
        'ta': "தயவுசெய்து உங்கள் பெயரை மட்டும் டைப் செய்யுங்கள். 🙂",
        'tanglish': "Unga peyar mattum type pannunga podhum. 🙂",
    },
    'ask_business': {
        'en': "What is your business name? (Tap *Skip* if you don't have one yet.)",
        'ta': "உங்கள் வணிகத்தின் பெயர் என்ன? (இன்னும் இல்லையெனில் *தவிர்* தட்டுங்கள்.)",
        'tanglish': "Unga business peyar enna? (Innum illana *Skip* tap pannunga.)",
    },
    'ask_services': {
        'en': "Which service do you need?",
        'ta': "உங்களுக்கு எந்தச் சேவை தேவை?",
        'tanglish': "Ungalukku endha service venum?",
    },
    'ask_services_button': {'en': "Choose service", 'ta': "சேவையைத் தேர்வு", 'tanglish': "Service choose"},
    'svc_added': {
        'en': "Added: *{svc}* ✅\nDo you need anything else?",
        'ta': "சேர்க்கப்பட்டது: *{svc}* ✅\nவேறு ஏதாவது தேவையா?",
        'tanglish': "Add pannitten: *{svc}* ✅\nVera edhaavadhu venumaa?",
    },
    'b_add_more': {'en': "➕ Add another", 'ta': "➕ இன்னொன்று", 'tanglish': "➕ Innonnu add"},
    'b_done': {'en': "✅ Done", 'ta': "✅ முடிந்தது", 'tanglish': "✅ Podhum"},
    'ask_timeline': {
        'en': "When do you need it?",
        'ta': "இது உங்களுக்கு எப்போது தேவை?",
        'tanglish': "Idhu ungalukku eppo venum?",
    },
    'ask_timeline_button': {'en': "Choose timeline", 'ta': "காலத்தைத் தேர்வு", 'tanglish': "Time choose"},
    'tl_asap': {'en': "As soon as possible", 'ta': "கூடிய விரைவில்", 'tanglish': "Seekiram venum"},
    'tl_1m': {'en': "Within a month", 'ta': "ஒரு மாதத்திற்குள்", 'tanglish': "Oru maasathukulla"},
    'tl_3m': {'en': "1–3 months", 'ta': "1–3 மாதங்கள்", 'tanglish': "1–3 maasam"},
    'tl_explore': {'en': "Just exploring", 'ta': "சும்மா தெரிந்துகொள்ள", 'tanglish': "Summa therinjukka"},
    'ask_method': {
        'en': "How should our team contact you?",
        'ta': "எங்கள் குழு உங்களை எப்படித் தொடர்புகொள்ள வேண்டும்?",
        'tanglish': "Engal team ungala eppadi contact pannanum?",
    },
    'cm_whatsapp': {'en': "💬 WhatsApp", 'ta': "💬 வாட்ஸ்அப்", 'tanglish': "💬 WhatsApp"},
    'cm_call': {'en': "📞 Phone call", 'ta': "📞 போன் அழைப்பு", 'tanglish': "📞 Phone call"},
    'cm_email': {'en': "✉️ Email", 'ta': "✉️ மின்னஞ்சல்", 'tanglish': "✉️ Email"},
    'ask_email_required': {
        'en': "Please type your email address. ✉️",
        'ta': "உங்கள் மின்னஞ்சல் முகவரியை டைப் செய்யுங்கள். ✉️",
        'tanglish': "Unga email address type pannunga. ✉️",
    },
    'ask_email_optional': {
        'en': "What is your email address? (optional — tap *Skip* if you prefer not to share)",
        'ta': "உங்கள் மின்னஞ்சல் முகவரி என்ன? (விருப்பம் — வேண்டாமெனில் *தவிர்* தட்டுங்கள்)",
        'tanglish': "Unga email address enna? (optional — venaamna *Skip* tap pannunga)",
    },
    'bad_email': {
        'en': "That email doesn't look right. Please check it and type it again.",
        'ta': "அந்த மின்னஞ்சல் சரியாகத் தெரியவில்லை. சரிபார்த்து மீண்டும் டைப் செய்யுங்கள்.",
        'tanglish': "Andha email sariyaa illa. Check panni thirumba type pannunga.",
    },
    'ask_phone': {
        'en': "We'll contact you on *{phone}*. Is that the right number?",
        'ta': "உங்களை *{phone}* எண்ணில் தொடர்புகொள்வோம். இது சரியான எண்ணா?",
        'tanglish': "Ungala *{phone}* number-la contact pannuvom. Idhu correct number-aa?",
    },
    'b_other_number': {'en': "📞 Other number", 'ta': "📞 வேறு எண்", 'tanglish': "📞 Vera number"},
    'ask_phone_type': {
        'en': "Please type the best phone number to reach you.",
        'ta': "உங்களைத் தொடர்புகொள்ள சிறந்த போன் எண்ணை டைப் செய்யுங்கள்.",
        'tanglish': "Ungala contact panna best phone number type pannunga.",
    },
    'bad_phone': {
        'en': "Please type a valid phone number with at least 10 digits.",
        'ta': "குறைந்தது 10 இலக்கங்கள் கொண்ட சரியான போன் எண்ணை டைப் செய்யுங்கள்.",
        'tanglish': "Kuraindhadhu 10 digits irukura correct phone number type pannunga.",
    },
    'ask_message': {
        'en': "Tell us a little about your project — what should we build? You can type or send a voice note. 🎙️",
        'ta': "உங்கள் திட்டத்தைப் பற்றி கொஞ்சம் சொல்லுங்கள் — நாங்கள் என்ன உருவாக்க வேண்டும்? டைப் செய்யலாம் அல்லது voice note அனுப்பலாம். 🎙️",
        'tanglish': "Unga project pathi konjam sollunga — naanga enna build pannanum? Type pannalaam illa voice note anuppalaam. 🎙️",
    },
    'summary': {
        'en': "Please check your details:\n\n👤 *Name:* {name}\n🏢 *Business:* {business}\n🛠️ *Services:* {services}\n⏱️ *When:* {timeline}\n📞 *Contact by:* {method}\n📱 *Phone:* {phone}\n✉️ *Email:* {email}\n📝 *Project:* {message}",
        'ta': "உங்கள் விவரங்களைச் சரிபாருங்கள்:\n\n👤 *பெயர்:* {name}\n🏢 *வணிகம்:* {business}\n🛠️ *சேவைகள்:* {services}\n⏱️ *எப்போது:* {timeline}\n📞 *தொடர்பு முறை:* {method}\n📱 *போன்:* {phone}\n✉️ *மின்னஞ்சல்:* {email}\n📝 *திட்டம்:* {message}",
        'tanglish': "Unga details-ah check pannunga:\n\n👤 *Peyar:* {name}\n🏢 *Business:* {business}\n🛠️ *Services:* {services}\n⏱️ *Eppo:* {timeline}\n📞 *Contact:* {method}\n📱 *Phone:* {phone}\n✉️ *Email:* {email}\n📝 *Project:* {message}",
    },
    'not_given': {'en': "—", 'ta': "—", 'tanglish': "—"},
    'b_submit': {'en': "✅ Submit", 'ta': "✅ அனுப்பு", 'tanglish': "✅ Submit"},
    'b_edit': {'en': "✏️ Edit", 'ta': "✏️ மாற்று", 'tanglish': "✏️ Edit"},
    'b_cancel': {'en': "❌ Cancel", 'ta': "❌ ரத்து", 'tanglish': "❌ Cancel"},
    'edit_which': {
        'en': "What would you like to change?",
        'ta': "எதை மாற்ற விரும்புகிறீர்கள்?",
        'tanglish': "Edha maathanum?",
    },
    'edit_button': {'en': "Choose", 'ta': "தேர்வு", 'tanglish': "Choose"},
    'f_name': {'en': "Name", 'ta': "பெயர்", 'tanglish': "Peyar"},
    'f_business': {'en': "Business name", 'ta': "வணிகப் பெயர்", 'tanglish': "Business peyar"},
    'f_services': {'en': "Services", 'ta': "சேவைகள்", 'tanglish': "Services"},
    'f_timeline': {'en': "When you need it", 'ta': "எப்போது தேவை", 'tanglish': "Eppo venum"},
    'f_method': {'en': "Contact method", 'ta': "தொடர்பு முறை", 'tanglish': "Contact method"},
    'f_email': {'en': "Email", 'ta': "மின்னஞ்சல்", 'tanglish': "Email"},
    'f_phone': {'en': "Phone number", 'ta': "போன் எண்", 'tanglish': "Phone number"},
    'f_message': {'en': "Project details", 'ta': "திட்ட விவரம்", 'tanglish': "Project details"},
    'enq_done': {
        'en': "✅ Thank you, {name}! Your enquiry *#{id}* is received.\nOur team will contact you *within 24 hours* with a free, clear quote. 🙏",
        'ta': "✅ நன்றி {name}! உங்கள் விசாரணை *#{id}* பெறப்பட்டது.\nஎங்கள் குழு *24 மணி நேரத்திற்குள்* இலவச, தெளிவான மதிப்பீட்டுடன் உங்களைத் தொடர்புகொள்ளும். 🙏",
        'tanglish': "✅ Nandri {name}! Unga enquiry *#{id}* kedaichiduchu.\nEngal team *24 hours-kulla* free, clear quote-oda ungala contact pannuvanga. 🙏",
    },
    'enq_next': {
        'en': "Would you like to book a call with our team?",
        'ta': "எங்கள் குழுவுடன் ஒரு அழைப்பைப் பதிவு செய்ய விரும்புகிறீர்களா?",
        'tanglish': "Engal team-oda oru call book pannanumaa?",
    },
    'enq_already': {
        'en': "Your enquiry is already submitted ✅ Our team will contact you within 24 hours.",
        'ta': "உங்கள் விசாரணை ஏற்கனவே அனுப்பப்பட்டது ✅ 24 மணி நேரத்திற்குள் எங்கள் குழு தொடர்புகொள்ளும்.",
        'tanglish': "Unga enquiry already submit aayiduchu ✅ 24 hours-kulla engal team contact pannuvanga.",
    },

    # ------------------------------------------------------------------ booking
    'bk_start': {
        'en': "Let's book a *free call* with our team. 📅",
        'ta': "எங்கள் குழுவுடன் *இலவச அழைப்பை* பதிவு செய்வோம். 📅",
        'tanglish': "Engal team-oda *free call* book pannalaam. 📅",
    },
    'bk_existing': {
        'en': "You already have a call booked for *{when}*.\nWhat would you like to do?",
        'ta': "*{when}* அன்று உங்களுக்கு ஏற்கனவே ஒரு அழைப்பு பதிவாகியுள்ளது.\nஎன்ன செய்ய விரும்புகிறீர்கள்?",
        'tanglish': "*{when}*-ku ungalukku already oru call book aagi irukku.\nEnna pannanum?",
    },
    'b_change_time': {'en': "🔁 Change time", 'ta': "🔁 நேரம் மாற்று", 'tanglish': "🔁 Time maathu"},
    'b_cancel_call': {'en': "❌ Cancel call", 'ta': "❌ அழைப்பு ரத்து", 'tanglish': "❌ Call cancel"},
    'b_keep': {'en': "👍 Keep it", 'ta': "👍 அப்படியே", 'tanglish': "👍 Appadiye"},
    'bk_ask_day': {
        'en': "Which day suits you?",
        'ta': "எந்த நாள் உங்களுக்கு வசதி?",
        'tanglish': "Endha naal ungalukku convenient?",
    },
    'bk_day_button': {'en': "Choose a day", 'ta': "நாளைத் தேர்வு", 'tanglish': "Naal choose"},
    'bk_ask_time': {
        'en': "What time on *{day}*? (India time)",
        'ta': "*{day}* அன்று எந்த நேரம்? (இந்திய நேரம்)",
        'tanglish': "*{day}* anniku endha time? (India time)",
    },
    'bk_time_button': {'en': "Choose a time", 'ta': "நேரத்தைத் தேர்வு", 'tanglish': "Time choose"},
    'bk_slots_left': {'en': "{n} slots free", 'ta': "{n} நேரங்கள் உள்ளன", 'tanglish': "{n} slots free"},
    'bk_today': {'en': "Today", 'ta': "இன்று", 'tanglish': "Indru"},
    'bk_tomorrow': {'en': "Tomorrow", 'ta': "நாளை", 'tanglish': "Naalai"},
    'bk_no_slots': {
        'en': "Sorry, all call times for the next few days are full. Our team will contact you within 24 hours to fix a time. 🙏",
        'ta': "மன்னிக்கவும், அடுத்த சில நாட்களுக்கான அழைப்பு நேரங்கள் நிரம்பிவிட்டன. நேரத்தை முடிவு செய்ய எங்கள் குழு 24 மணி நேரத்திற்குள் தொடர்புகொள்ளும். 🙏",
        'tanglish': "Sorry, adutha konja naal call times ellam full. Time fix panna engal team 24 hours-kulla contact pannuvanga. 🙏",
    },
    'bk_day_full': {
        'en': "Sorry, that day is full now. Please choose another day.",
        'ta': "மன்னிக்கவும், அந்த நாள் நிரம்பிவிட்டது. வேறு நாளைத் தேர்ந்தெடுங்கள்.",
        'tanglish': "Sorry, andha naal full aayiduchu. Vera naal choose pannunga.",
    },
    'bk_slot_taken': {
        'en': "Sorry, that time was just booked by someone else. Please pick another time.",
        'ta': "மன்னிக்கவும், அந்த நேரம் இப்போது வேறொருவரால் பதிவு செய்யப்பட்டது. வேறு நேரத்தைத் தேர்ந்தெடுங்கள்.",
        'tanglish': "Sorry, andha time ippo dhaan vera oruthar book pannitaanga. Vera time choose pannunga.",
    },
    'bk_bad_time': {
        'en': "Please choose a day and time from the list. 👇",
        'ta': "பட்டியலிலிருந்து நாளையும் நேரத்தையும் தேர்ந்தெடுங்கள். 👇",
        'tanglish': "List-la irundhu naal-um time-um choose pannunga. 👇",
    },
    'bk_ask_topic': {
        'en': "What would you like to discuss on the call? (optional)",
        'ta': "அழைப்பில் எதைப் பற்றிப் பேச விரும்புகிறீர்கள்? (விருப்பம்)",
        'tanglish': "Call-la edha pathi pesanum? (optional)",
    },
    'bk_confirm': {
        'en': "Please confirm your call:\n\n📅 *{when}*\n📱 {phone}\n📝 {topic}",
        'ta': "உங்கள் அழைப்பை உறுதி செய்யுங்கள்:\n\n📅 *{when}*\n📱 {phone}\n📝 {topic}",
        'tanglish': "Unga call-ah confirm pannunga:\n\n📅 *{when}*\n📱 {phone}\n📝 {topic}",
    },
    'b_confirm': {'en': "✅ Confirm", 'ta': "✅ உறுதி", 'tanglish': "✅ Confirm"},
    'bk_done': {
        'en': "✅ Your call is booked for *{when}*.\nOur team will call you on {phone}. To change it, just type *change call*.",
        'ta': "✅ உங்கள் அழைப்பு *{when}* அன்று பதிவாகியுள்ளது.\nஎங்கள் குழு {phone} எண்ணில் அழைக்கும். மாற்ற *change call* என டைப் செய்யுங்கள்.",
        'tanglish': "✅ Unga call *{when}*-ku book aayiduchu.\nEngal team {phone}-ku call pannuvanga. Maathanum na *change call* nu type pannunga.",
    },
    'bk_cancelled': {
        'en': "Your call on *{when}* is cancelled. You can book again anytime from the menu.",
        'ta': "*{when}* அன்றைய உங்கள் அழைப்பு ரத்து செய்யப்பட்டது. மெனுவிலிருந்து எப்போது வேண்டுமானாலும் மீண்டும் பதிவு செய்யலாம்.",
        'tanglish': "*{when}* call cancel aayiduchu. Menu-la irundhu eppo venumnaalum thirumba book pannalaam.",
    },
    'bk_kept': {
        'en': "Great, your call stays on *{when}*. 👍",
        'ta': "சரி, உங்கள் அழைப்பு *{when}* அன்றே இருக்கும். 👍",
        'tanglish': "Seri, unga call *{when}*-ke irukkum. 👍",
    },
    'bk_reminder': {
        'en': "⏰ Reminder: your call with AJ Technologies is today at *{time}*. Our team will call you on {phone}.",
        'ta': "⏰ நினைவூட்டல்: AJ Technologies உடனான உங்கள் அழைப்பு இன்று *{time}* மணிக்கு. எங்கள் குழு {phone} எண்ணில் அழைக்கும்.",
        'tanglish': "⏰ Reminder: AJ Technologies-oda unga call indru *{time}*-ku. Engal team {phone}-ku call pannuvanga.",
    },

    # ------------------------------------------------------------------ portfolio
    'pf_intro': {
        'en': "Here are some projects we've built. Tap one to see it. 👇",
        'ta': "நாங்கள் உருவாக்கிய சில திட்டங்கள் இதோ. பார்க்க ஒன்றைத் தட்டுங்கள். 👇",
        'tanglish': "Naanga build panna sila projects idho. Paarkka onna tap pannunga. 👇",
    },
    'pf_button': {'en': "View projects", 'ta': "திட்டங்கள்", 'tanglish': "Projects paaru"},
    'pf_none': {
        'en': "We're adding our latest work right now. You can see our portfolio here:\n{url}",
        'ta': "எங்கள் சமீபத்திய படைப்புகளை இப்போது சேர்த்துக்கொண்டிருக்கிறோம். எங்கள் portfolio-வை இங்கே பார்க்கலாம்:\n{url}",
        'tanglish': "Engal latest work-ah ippo add pannittu irukkom. Engal portfolio-va inga paakkalaam:\n{url}",
    },
    'pf_live': {'en': "🔗 Live: {url}", 'ta': "🔗 நேரலை: {url}", 'tanglish': "🔗 Live: {url}"},
    'pf_soon': {'en': "🔗 Live link coming soon", 'ta': "🔗 நேரலை இணைப்பு விரைவில்", 'tanglish': "🔗 Live link seekiram"},
    'pf_next': {
        'en': "Would you like something like this for your business?",
        'ta': "உங்கள் வணிகத்திற்கும் இதுபோல் வேண்டுமா?",
        'tanglish': "Unga business-kum idhu maadhiri venumaa?",
    },
    'b_more_projects': {'en': "📂 More projects", 'ta': "📂 மேலும் திட்டங்கள்", 'tanglish': "📂 Innum projects"},
    'pf_all': {
        'en': "See all our work on the website: {url}",
        'ta': "எங்கள் அனைத்துப் படைப்புகளையும் இணையதளத்தில் பாருங்கள்: {url}",
        'tanglish': "Engal ella work-um website-la paarunga: {url}",
    },

    # ------------------------------------------------------------------ reviews
    'rv_start': {
        'en': "Thank you for taking a moment to review us! 🙏",
        'ta': "எங்களை மதிப்பிட நேரம் ஒதுக்கியதற்கு நன்றி! 🙏",
        'tanglish': "Engala review panna time kuduthadhukku nandri! 🙏",
    },
    'rv_ask_rating': {
        'en': "How would you rate your experience with AJ Technologies?",
        'ta': "AJ Technologies உடனான உங்கள் அனுபவத்தை எப்படி மதிப்பிடுவீர்கள்?",
        'tanglish': "AJ Technologies-oda unga experience-ku evvalavu rating kuduppeenga?",
    },
    'rv_rating_button': {'en': "Choose rating", 'ta': "மதிப்பீடு", 'tanglish': "Rating choose"},
    'rv_5': {'en': "Excellent", 'ta': "மிகச் சிறப்பு", 'tanglish': "Romba super"},
    'rv_4': {'en': "Very good", 'ta': "மிக நன்று", 'tanglish': "Romba nalla"},
    'rv_3': {'en': "Good", 'ta': "நன்று", 'tanglish': "Nalla"},
    'rv_2': {'en': "Could be better", 'ta': "இன்னும் மேம்படலாம்", 'tanglish': "Innum better aagalaam"},
    'rv_1': {'en': "Not happy", 'ta': "திருப்தி இல்லை", 'tanglish': "Thirupthi illa"},
    'rv_ask_text': {
        'en': "Please write a few lines about your experience (or send a voice note). 🎙️",
        'ta': "உங்கள் அனுபவத்தைப் பற்றி சில வரிகள் எழுதுங்கள் (அல்லது voice note அனுப்புங்கள்). 🎙️",
        'tanglish': "Unga experience pathi sila lines ezhudhunga (illa voice note anuppunga). 🎙️",
    },
    'rv_too_short': {
        'en': "Please write at least a few words. 🙂",
        'ta': "தயவுசெய்து குறைந்தது சில வார்த்தைகள் எழுதுங்கள். 🙂",
        'tanglish': "Kuraindhadhu sila words ezhudhunga. 🙂",
    },
    'rv_ask_name': {
        'en': "What name should we show with your review?",
        'ta': "உங்கள் விமர்சனத்துடன் எந்தப் பெயரைக் காட்டலாம்?",
        'tanglish': "Unga review-oda endha peyar kaattalaam?",
    },
    'rv_ask_biz': {
        'en': "Your business name and town? e.g. *Sri Murugan Traders, Thoothukudi* (optional)",
        'ta': "உங்கள் வணிகப் பெயர் மற்றும் ஊர்? எ.கா. *ஸ்ரீ முருகன் டிரேடர்ஸ், தூத்துக்குடி* (விருப்பம்)",
        'tanglish': "Unga business peyar matrum ooru? e.g. *Sri Murugan Traders, Thoothukudi* (optional)",
    },
    'rv_ask_publish': {
        'en': "Can we show your review on our website?",
        'ta': "உங்கள் விமர்சனத்தை எங்கள் இணையதளத்தில் காட்டலாமா?",
        'tanglish': "Unga review-ah engal website-la kaattalaamaa?",
    },
    'b_publish_yes': {'en': "✅ Yes, you can", 'ta': "✅ ஆம், காட்டலாம்", 'tanglish': "✅ Kaattalaam"},
    'b_publish_no': {'en': "🙈 Keep it private", 'ta': "🙈 வேண்டாம்", 'tanglish': "🙈 Venaam"},
    'rv_done_public': {
        'en': "Thank you so much, {name}! 🙏 Your review will appear on our website after a quick check.",
        'ta': "மிக்க நன்றி {name}! 🙏 ஒரு சிறு சரிபார்ப்புக்குப் பின் உங்கள் விமர்சனம் எங்கள் இணையதளத்தில் தோன்றும்.",
        'tanglish': "Romba nandri {name}! 🙏 Oru chinna check-ku apram unga review engal website-la varum.",
    },
    'rv_done_private': {
        'en': "Thank you, {name}! 🙏 We've shared your feedback with our team. It will not be published.",
        'ta': "நன்றி {name}! 🙏 உங்கள் கருத்தை எங்கள் குழுவிடம் பகிர்ந்துள்ளோம். இது வெளியிடப்படாது.",
        'tanglish': "Nandri {name}! 🙏 Unga feedback-ah engal team kitta share pannittom. Idhu publish aagaadhu.",
    },
    'rv_google': {
        'en': "If you have a minute, posting it on Google too helps us a lot: {url}",
        'ta': "நேரம் இருந்தால், Google-இலும் பதிவிடுவது எங்களுக்குப் பெரிதும் உதவும்: {url}",
        'tanglish': "Time irundha, Google-layum post panna engalukku romba help-ah irukkum: {url}",
    },
    'rv_request': {
        'en': "Hello {name}! 🙏 Thank you for choosing AJ Technologies. Could you share a short review of your experience? It really helps us.",
        'ta': "வணக்கம் {name}! 🙏 AJ Technologies-ஐத் தேர்ந்தெடுத்ததற்கு நன்றி. உங்கள் அனுபவத்தைப் பற்றி ஒரு சிறு விமர்சனம் பகிர முடியுமா? இது எங்களுக்குப் பெரிதும் உதவும்.",
        'tanglish': "Vanakkam {name}! 🙏 AJ Technologies-ah choose pannadhukku nandri. Unga experience pathi oru chinna review share panna mudiyumaa? Engalukku romba help-ah irukkum.",
    },
    'b_write_review': {'en': "⭐ Write a review", 'ta': "⭐ விமர்சனம் எழுது", 'tanglish': "⭐ Review ezhudhu"},

    # ------------------------------------------------------------------ language
    'lang_ask': {
        'en': "Choose your language:",
        'ta': "உங்கள் மொழியைத் தேர்ந்தெடுங்கள்:",
        'tanglish': "Unga language-ah choose pannunga:",
    },
    'lang_button': {'en': "Choose language", 'ta': "மொழி", 'tanglish': "Language"},
    'lang_auto': {'en': "🔄 Auto-detect", 'ta': "🔄 தானாகக் கண்டறி", 'tanglish': "🔄 Auto-detect"},
    'lang_auto_d': {'en': "Reply in the language I type", 'ta': "நான் எழுதும் மொழியில் பதில்", 'tanglish': "Naan type panra language-la reply"},
    'lang_set': {
        'en': "Done! I'll reply in English from now on. 👍",
        'ta': "சரி! இனி தமிழில் பதில் அளிக்கிறேன். 👍",
        'tanglish': "Seri! Ini Tanglish-la reply pannuren. 👍",
    },
    'lang_set_auto': {
        'en': "Done! I'll reply in whatever language you write in. 👍",
        'ta': "சரி! நீங்கள் எழுதும் மொழியிலேயே பதில் அளிக்கிறேன். 👍",
        'tanglish': "Seri! Neenga endha language-la type panreengalo adhulaye reply pannuren. 👍",
    },

    # ------------------------------------------------------------------ opt-out
    'stop_done': {
        'en': "Done. You won't receive offers from us anymore. You can still message us anytime. To get offers again, send *START*.",
        'ta': "சரி. இனி எங்களிடமிருந்து சலுகைச் செய்திகள் வராது. எப்போது வேண்டுமானாலும் எங்களுக்குச் செய்தி அனுப்பலாம். மீண்டும் சலுகைகள் பெற *START* அனுப்புங்கள்.",
        'tanglish': "Seri. Ini engal kitta irundhu offers varaadhu. Eppo venumnaalum message pannalaam. Thirumba offers venum na *START* anuppunga.",
    },
    'start_done': {
        'en': "You're subscribed to our offers again. 🎉 Send *STOP* anytime to stop.",
        'ta': "எங்கள் சலுகைகளுக்கு மீண்டும் இணைந்துவிட்டீர்கள். 🎉 நிறுத்த எப்போது வேண்டுமானாலும் *STOP* அனுப்புங்கள்.",
        'tanglish': "Thirumba engal offers-ku subscribe aayitteenga. 🎉 Stop panna eppo venumnaalum *STOP* anuppunga.",
    },

    # ------------------------------------------------------------------ follow-up
    'nudge': {
        'en': "Hi {name}, you were in the middle of {what} with us. Would you like to continue? 🙂",
        'ta': "வணக்கம் {name}, நீங்கள் எங்களுடன் {what} பாதியில் இருந்தீர்கள். தொடரலாமா? 🙂",
        'tanglish': "Vanakkam {name}, neenga engaloda {what} paadhiyila irundheenga. Continue pannalaamaa? 🙂",
    },
    'what_enquiry': {'en': "your quote request", 'ta': "மதிப்பீட்டுக் கோரிக்கை", 'tanglish': "quote request"},
    'what_booking': {'en': "booking a call", 'ta': "அழைப்பு பதிவு", 'tanglish': "call booking"},
    'what_review': {'en': "your review", 'ta': "விமர்சனம்", 'tanglish': "review"},
    'b_continue': {'en': "▶️ Continue", 'ta': "▶️ தொடர்", 'tanglish': "▶️ Continue"},

    # ------------------------------------------------------------------ media
    'media_thanks': {
        'en': "Thanks, I've received it. 👍 Our team can see it too.",
        'ta': "நன்றி, கிடைத்தது. 👍 எங்கள் குழுவும் இதைப் பார்க்கும்.",
        'tanglish': "Nandri, kedaichiduchu. 👍 Engal team-um idha paarppanga.",
    },
    'voice_fail': {
        'en': "Sorry, I couldn't hear that voice note clearly. Could you type it, or send it again?",
        'ta': "மன்னிக்கவும், அந்த voice note சரியாகக் கேட்கவில்லை. டைப் செய்ய முடியுமா, அல்லது மீண்டும் அனுப்புங்கள்?",
        'tanglish': "Sorry, andha voice note sariyaa kekkala. Type panna mudiyumaa, illa thirumba anuppunga?",
    },
    'unsupported': {
        'en': "Sorry, I can't open that type of message. Please type your message. 🙂",
        'ta': "மன்னிக்கவும், அந்த வகைச் செய்தியை என்னால் திறக்க முடியவில்லை. உங்கள் செய்தியை டைப் செய்யுங்கள். 🙂",
        'tanglish': "Sorry, andha type message-ah enakku open panna mudiyala. Unga message-ah type pannunga. 🙂",
    },
}

# ---------------------------------------------------------------------------
# Upgrade v2: off-topic, client projects, support requests, follow-ups, renewals
# ---------------------------------------------------------------------------
T.update({
    'off_topic': {
        'en': "I'm *AJ Technologies Assistant* 🙂 I can help only with AJ Technologies and our websites, apps, software and digital marketing services. Is there anything I can help you with on that?",
        'ta': "நான் *AJ Technologies Assistant* 🙂 AJ Technologies மற்றும் எங்கள் இணையதளம், ஆப்ஸ், மென்பொருள், டிஜிட்டல் மார்க்கெட்டிங் சேவைகள் பற்றி மட்டுமே என்னால் உதவ முடியும். அதைப் பற்றி ஏதாவது உதவி வேண்டுமா?",
        'tanglish': "Naan *AJ Technologies Assistant* 🙂 AJ Technologies matrum engal website, apps, software, digital marketing services pathi mattum dhaan help panna mudiyum. Adhu pathi edhaavadhu help venumaa?",
    },
    'what_support': {'en': "your support request", 'ta': "உதவி கோரிக்கை", 'tanglish': "support request"},
    'm_project': {'en': "📊 My project", 'ta': "📊 என் திட்டம்", 'tanglish': "📊 En project"},
    'm_project_d': {'en': "For clients: status of your project", 'ta': "வாடிக்கையாளர்களுக்கு: திட்ட நிலை", 'tanglish': "Clients-ku: project status"},
    'm_support': {'en': "🛠️ Support request", 'ta': "🛠️ உதவி கோரிக்கை", 'tanglish': "🛠️ Support request"},
    'm_support_d': {'en': "Report a problem or ask for a change", 'ta': "சிக்கல் அல்லது மாற்றம் தெரிவிக்க", 'tanglish': "Problem illa change sollunga"},
    'b_project': {'en': "📊 My project", 'ta': "📊 என் திட்டம்", 'tanglish': "📊 En project"},
    'b_support': {'en': "🛠️ Support", 'ta': "🛠️ உதவி", 'tanglish': "🛠️ Support"},
    'b_team': {'en': "👤 Talk to team", 'ta': "👤 குழுவிடம் பேச", 'tanglish': "👤 Team kitta pesa"},
    'b_my_requests': {'en': "📋 My requests", 'ta': "📋 என் கோரிக்கைகள்", 'tanglish': "📋 En requests"},

    # project status (only the projects linked to THIS WhatsApp number)
    'ps_none': {
        'en': "I couldn't find a project linked to this WhatsApp number. 🙂 If you're already our client, our team can link it for you. If you'd like to start a new project, tap *Get a quote*.",
        'ta': "இந்த வாட்ஸ்அப் எண்ணுடன் இணைக்கப்பட்ட திட்டம் எதுவும் கிடைக்கவில்லை. 🙂 நீங்கள் ஏற்கனவே எங்கள் வாடிக்கையாளர் என்றால், எங்கள் குழு அதை இணைத்துத் தரும். புதிய திட்டம் தொடங்க *மதிப்பீடு பெற* தட்டுங்கள்.",
        'tanglish': "Indha WhatsApp number-oda link aana project edhuvum kedaikala. 🙂 Neenga already engal client-na, engal team adha link pannitharuvanga. Pudhu project-ku *Quote venum* tap pannunga.",
    },
    'ps_title': {'en': "📊 *Your project with AJ Technologies*", 'ta': "📊 *AJ Technologies உடனான உங்கள் திட்டம்*", 'tanglish': "📊 *AJ Technologies-oda unga project*"},
    'ps_title_many': {'en': "📊 *Your projects with AJ Technologies*", 'ta': "📊 *AJ Technologies உடனான உங்கள் திட்டங்கள்*", 'tanglish': "📊 *AJ Technologies-oda unga projects*"},
    'ps_stage': {'en': "Stage", 'ta': "நிலை", 'tanglish': "Stage"},
    'ps_progress': {'en': "Progress", 'ta': "முன்னேற்றம்", 'tanglish': "Progress"},
    'ps_update': {'en': "Latest update", 'ta': "சமீபத்திய தகவல்", 'tanglish': "Latest update"},
    'ps_live': {'en': "Live link", 'ta': "நேரலை இணைப்பு", 'tanglish': "Live link"},
    'ps_renewal': {'en': "Renewal", 'ta': "புதுப்பித்தல்", 'tanglish': "Renewal"},
    'ps_open_requests': {'en': "Open support requests: {n}", 'ta': "திறந்த உதவி கோரிக்கைகள்: {n}", 'tanglish': "Open support requests: {n}"},
    'ps_footer': {
        'en': "Questions about your project? Just type here, or tap *Support* to raise a request.",
        'ta': "திட்டம் பற்றிக் கேள்விகள் உள்ளதா? இங்கே டைப் செய்யுங்கள், அல்லது கோரிக்கை வைக்க *உதவி* தட்டுங்கள்.",
        'tanglish': "Project pathi questions irukkaa? Inga type pannunga, illa request-ku *Support* tap pannunga.",
    },
    'stage_requirement': {'en': "Requirements", 'ta': "தேவைகள்", 'tanglish': "Requirements"},
    'stage_design': {'en': "Design", 'ta': "வடிவமைப்பு", 'tanglish': "Design"},
    'stage_development': {'en': "Development", 'ta': "உருவாக்கம்", 'tanglish': "Development"},
    'stage_testing': {'en': "Testing", 'ta': "சோதனை", 'tanglish': "Testing"},
    'stage_launch': {'en': "Launch", 'ta': "வெளியீடு", 'tanglish': "Launch"},
    'stage_live': {'en': "Live ✅", 'ta': "நேரலையில் ✅", 'tanglish': "Live ✅"},
    'stage_support': {'en': "Support & maintenance", 'ta': "ஆதரவு & பராமரிப்பு", 'tanglish': "Support & maintenance"},
    'stage_on_hold': {'en': "On hold", 'ta': "நிறுத்தி வைக்கப்பட்டது", 'tanglish': "On hold"},
    'item_domain': {'en': "domain", 'ta': "டொமைன்", 'tanglish': "domain"},
    'item_hosting': {'en': "hosting", 'ta': "ஹோஸ்டிங்", 'tanglish': "hosting"},
    'item_ssl': {'en': "SSL certificate", 'ta': "SSL சான்றிதழ்", 'tanglish': "SSL certificate"},
    'item_amc': {'en': "maintenance plan (AMC)", 'ta': "பராமரிப்புத் திட்டம் (AMC)", 'tanglish': "maintenance plan (AMC)"},
    'item_email': {'en': "business email", 'ta': "வணிக மின்னஞ்சல்", 'tanglish': "business email"},
    'item_app_store': {'en': "app store account", 'ta': "ஆப் ஸ்டோர் கணக்கு", 'tanglish': "app store account"},
    'item_other': {'en': "service", 'ta': "சேவை", 'tanglish': "service"},

    # support requests
    'sp_start': {
        'en': "Sure, let's raise a support request. 🛠️ (Type *cancel* anytime to stop.)",
        'ta': "சரி, ஒரு உதவி கோரிக்கையைப் பதிவு செய்வோம். 🛠️ (நிறுத்த *cancel* என டைப் செய்யுங்கள்.)",
        'tanglish': "Seri, oru support request podalaam. 🛠️ (Stop panna *cancel* nu type pannunga.)",
    },
    'sp_pick_project': {'en': "Which project is this about?", 'ta': "இது எந்தத் திட்டம் பற்றியது?", 'tanglish': "Idhu endha project pathi?"},
    'sp_pick_button': {'en': "Choose project", 'ta': "திட்டத்தைத் தேர்வு", 'tanglish': "Project choose"},
    'sp_other_project': {'en': "Something else", 'ta': "வேறு ஏதாவது", 'tanglish': "Vera edhaavadhu"},
    'sp_ask_desc': {
        'en': "Please describe the problem or the change you need. You can type, send a voice note or a screenshot. 📎",
        'ta': "சிக்கலையோ தேவையான மாற்றத்தையோ விவரியுங்கள். டைப் செய்யலாம், voice note அல்லது screenshot அனுப்பலாம். 📎",
        'tanglish': "Problem illa venum-na change-ah sollunga. Type pannalaam, voice note illa screenshot anuppalaam. 📎",
    },
    'sp_more_detail': {
        'en': "Got it 👍 Please add a short description in words too, so our team understands it quickly.",
        'ta': "கிடைத்தது 👍 எங்கள் குழு விரைவாகப் புரிந்துகொள்ள, சில வார்த்தைகளிலும் விவரியுங்கள்.",
        'tanglish': "Kedaichiduchu 👍 Engal team seekiram purinjukka, konjam words-laiyum sollunga.",
    },
    'sp_ask_priority': {
        'en': "Is it urgent? (for example, your website or app is not working)",
        'ta': "இது அவசரமா? (எ.கா. உங்கள் இணையதளம் அல்லது ஆப் வேலை செய்யவில்லை)",
        'tanglish': "Idhu urgent-aa? (e.g. unga website illa app work aagala)",
    },
    'b_urgent': {'en': "🔴 Urgent", 'ta': "🔴 அவசரம்", 'tanglish': "🔴 Urgent"},
    'b_normal': {'en': "🟢 Not urgent", 'ta': "🟢 அவசரம் இல்லை", 'tanglish': "🟢 Urgent illa"},
    'sp_confirm': {
        'en': "Please confirm your request:\n\n📁 *Project:* {project}\n📝 {desc}\n⚡ *Priority:* {priority}",
        'ta': "உங்கள் கோரிக்கையை உறுதி செய்யுங்கள்:\n\n📁 *திட்டம்:* {project}\n📝 {desc}\n⚡ *முன்னுரிமை:* {priority}",
        'tanglish': "Unga request-ah confirm pannunga:\n\n📁 *Project:* {project}\n📝 {desc}\n⚡ *Priority:* {priority}",
    },
    'sp_done': {
        'en': "✅ Your support request *#{id}* is registered. Our team will update you right here. Type *my requests* anytime to see the status.",
        'ta': "✅ உங்கள் உதவி கோரிக்கை *#{id}* பதிவானது. எங்கள் குழு இங்கேயே தகவல் தரும். நிலையை அறிய எப்போது வேண்டுமானாலும் *my requests* என டைப் செய்யுங்கள்.",
        'tanglish': "✅ Unga support request *#{id}* register aayiduchu. Engal team inga update pannuvanga. Status paarkka eppo venumnaalum *my requests* nu type pannunga.",
    },
    'sp_list_title': {'en': "📋 *Your support requests*", 'ta': "📋 *உங்கள் உதவி கோரிக்கைகள்*", 'tanglish': "📋 *Unga support requests*"},
    'sp_list_none': {
        'en': "You have no support requests yet. Tap *Support* if you need help with your website or app.",
        'ta': "உங்களுக்கு இன்னும் உதவி கோரிக்கைகள் இல்லை. உதவி தேவைப்பட்டால் *உதவி* தட்டுங்கள்.",
        'tanglish': "Ungalukku innum support requests illa. Help venum-na *Support* tap pannunga.",
    },
    'tk_open': {'en': "Received", 'ta': "பெறப்பட்டது", 'tanglish': "Received"},
    'tk_in_progress': {'en': "In progress", 'ta': "நடைபெறுகிறது", 'tanglish': "In progress"},
    'tk_waiting': {'en': "Waiting for your reply", 'ta': "உங்கள் பதிலுக்காகக் காத்திருக்கிறது", 'tanglish': "Unga reply-ku waiting"},
    'tk_resolved': {'en': "Resolved ✅", 'ta': "தீர்க்கப்பட்டது ✅", 'tanglish': "Resolved ✅"},
    'tk_closed': {'en': "Closed", 'ta': "மூடப்பட்டது", 'tanglish': "Closed"},
    'tk_update': {
        'en': "🛠️ Update on your support request *#{id}*: *{status}*\n{note}",
        'ta': "🛠️ உங்கள் உதவி கோரிக்கை *#{id}* பற்றிய தகவல்: *{status}*\n{note}",
        'tanglish': "🛠️ Unga support request *#{id}* update: *{status}*\n{note}",
    },

    # old-lead follow-up replies
    'fu_not_now': {
        'en': "No problem at all! 🙏 Whenever you're ready, just message us here and we'll be happy to help.",
        'ta': "பரவாயில்லை! 🙏 நீங்கள் தயாரானதும் இங்கே செய்தி அனுப்புங்கள், மகிழ்ச்சியுடன் உதவுவோம்.",
        'tanglish': "Paravaayilla! 🙏 Neenga ready aanadhum inga message pannunga, sandhoshama help pannuvom.",
    },
    'fu_details': {
        'en': "Sure! Here are our services. Tap one for details, or ask me anything. Our team will also contact you soon. 🙂",
        'ta': "சரி! இதோ எங்கள் சேவைகள். விவரங்களுக்கு ஒன்றைத் தட்டுங்கள், அல்லது எதுவும் கேளுங்கள். எங்கள் குழுவும் விரைவில் தொடர்புகொள்ளும். 🙂",
        'tanglish': "Seri! Idho engal services. Details-ku onna tap pannunga, illa edhu venumnaalum kelunga. Engal team-um seekiram contact pannuvanga. 🙂",
    },

    # renewals
    'rn_thanks': {
        'en': "Thank you! 🙏 Our team will contact you shortly to renew it on time.",
        'ta': "நன்றி! 🙏 சரியான நேரத்தில் புதுப்பிக்க எங்கள் குழு விரைவில் தொடர்புகொள்ளும்.",
        'tanglish': "Nandri! 🙏 Time-ku renew panna engal team seekiram contact pannuvanga.",
    },

    'rn_reminder': {
        'en': "🔁 Reminder from AJ Technologies: your {item} *{label}* expires on *{date}* ({days} days left). Shall we renew it for you?",
        'ta': "🔁 AJ Technologies நினைவூட்டல்: உங்கள் {item} *{label}* *{date}* அன்று காலாவதியாகிறது (இன்னும் {days} நாட்கள்). நாங்கள் புதுப்பிக்கலாமா?",
        'tanglish': "🔁 AJ Technologies reminder: unga {item} *{label}* *{date}* anniku expire aagudhu (innum {days} naal). Naanga renew pannalaamaa?",
    },
    'b_renew': {'en': "✅ Renew it", 'ta': "✅ புதுப்பிக்கவும்", 'tanglish': "✅ Renew pannunga"},
    'b_call_me': {'en': "📞 Call me", 'ta': "📞 அழையுங்கள்", 'tanglish': "📞 Call pannunga"},
    # project update (sent from the dashboard while the 24-hour window is open)
    'pu_update': {
        'en': "📊 Update on your project *{title}*: *{stage}* ({progress}%)\n{note}",
        'ta': "📊 உங்கள் திட்டம் *{title}* பற்றிய தகவல்: *{stage}* ({progress}%)\n{note}",
        'tanglish': "📊 Unga project *{title}* update: *{stage}* ({progress}%)\n{note}",
    },
})

LANG_SET_OTHER = "Done! I'll reply in {language} from now on. 👍"


class _Safe(dict):
    def __missing__(self, key):
        return ''


def _fmt(text, values):
    try:
        return string.Formatter().vformat(text, (), _Safe(values))
    except (ValueError, IndexError):
        return text


def t(lang, key, **values):
    """One text in the customer's language."""
    entry = T[key]
    if lang in BUILTIN:
        return _fmt(entry.get(lang) or entry['en'], values)
    english = _fmt(entry['en'], values)
    import ai  # imported here to avoid a circular import
    return ai.translate(english, lang)


def t_many(lang, keys_or_texts):
    """Several short labels at once (buttons, list rows). Items are text keys or (key, values) pairs."""
    resolved = []
    for item in keys_or_texts:
        key, values = (item if isinstance(item, tuple) else (item, {}))
        resolved.append((key, values))
    if lang in BUILTIN:
        return [_fmt(T[k].get(lang) or T[k]['en'], v) for k, v in resolved]
    english = [_fmt(T[k]['en'], v) for k, v in resolved]
    import ai
    return ai.translate_many(english, lang)


def raw(lang, text):
    """Free text (not from the table) in the customer's language."""
    if lang == 'en':
        return text
    import ai
    return ai.translate(text, 'tanglish' if lang == 'tanglish' else lang)