import 'package:flutter/material.dart';

/// Localisation for English, Marathi and Hindi.
///
/// Implemented directly (rather than with generated ARB files) because the app
/// ships exactly three languages, needs no plural machinery, and this keeps the
/// translation table reviewable in one place. [AppLocalizations.missingKeys]
/// exists so a test can fail the build when a string is added to one language
/// but forgotten in another — a farmer must never see a raw `dashboard_title`.
class AppLocalizations {
  const AppLocalizations(this.locale);

  final Locale locale;

  static const List<Locale> supportedLocales = [
    Locale('en'),
    Locale('mr'),
    Locale('hi'),
  ];

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  static AppLocalizations of(BuildContext context) =>
      Localizations.of<AppLocalizations>(context, AppLocalizations) ??
      const AppLocalizations(Locale('en'));

  /// Look up a key. Resolution order: the active language, then English, then the
  /// key itself (which is a visible, greppable bug rather than an empty label).
  String t(String key) {
    final table = _strings[key];
    if (table == null) return key;
    final value = table[locale.languageCode];
    if (value != null && value.isNotEmpty) return value;
    return table['en'] ?? key;
  }

  /// [t] with `{name}` placeholders filled in. The values are addresses, ports
  /// and counts — never translated text — so they are inserted verbatim.
  String tf(String key, Map<String, String> values) {
    var text = t(key);
    values.forEach((name, value) => text = text.replaceAll('{$name}', value));
    return text;
  }

  /// Convenience for values that may be null.
  String tn(String key, String? value) =>
      (value == null || value.isEmpty) ? t('not_recorded') : value;

  /// Keys missing from one or more languages. Used by the widget test.
  static List<String> missingKeys() {
    return _strings.entries
        .where(
          (entry) => supportedLocales.any(
            (locale) => (entry.value[locale.languageCode] ?? '').isEmpty,
          ),
        )
        .map((entry) => entry.key)
        .toList();
  }

  /// True when [key] exists in the table, regardless of language. Used by the
  /// test that scans `lib/` for `context.t('...')` calls, so a typo in a screen
  /// fails the build instead of showing the raw key to a farmer.
  static bool hasKey(String key) => _strings.containsKey(key);

  static const Map<String, Map<String, String>> _strings = {
    // ------------------------------------------------------------------ app
    'app_title': {
      'en': 'Digital Village',
      'mr': 'डिजिटल व्हिलेज',
      'hi': 'डिजिटल विलेज'
    },
    'app_tagline': {
      'en': 'Farming information, from real sources',
      'mr': 'खात्रीशीर स्रोतांकडून शेती माहिती',
      'hi': 'भरोसेमंद स्रोतों से खेती की जानकारी',
    },
    // --------------------------------------------------------------- common
    'retry': {'en': 'Retry', 'mr': 'पुन्हा प्रयत्न', 'hi': 'फिर कोशिश करें'},
    'ok': {'en': 'OK', 'mr': 'ठीक', 'hi': 'ठीक है'},
    'loading': {'en': 'Loading…', 'mr': 'लोड होत आहे…', 'hi': 'लोड हो रहा है…'},
    'error_title': {
      'en': 'Something went wrong',
      'mr': 'काहीतरी चुकले',
      'hi': 'कुछ गड़बड़ हुई'
    },
    'empty_title': {
      'en': 'Nothing here yet',
      'mr': 'अजून काही नाही',
      'hi': 'अभी कुछ नहीं'
    },
    'save': {'en': 'Save', 'mr': 'जतन करा', 'hi': 'सेव करें'},
    'cancel': {'en': 'Cancel', 'mr': 'रद्द करा', 'hi': 'रद्द करें'},
    'close': {'en': 'Close', 'mr': 'बंद करा', 'hi': 'बंद करें'},
    'delete': {'en': 'Delete', 'mr': 'हटवा', 'hi': 'हटाएँ'},
    'edit': {'en': 'Edit', 'mr': 'बदला', 'hi': 'बदलें'},
    'add': {'en': 'Add', 'mr': 'जोडा', 'hi': 'जोड़ें'},
    'search': {'en': 'Search', 'mr': 'शोध', 'hi': 'खोजें'},
    'filters': {'en': 'Filters', 'mr': 'गाळणी', 'hi': 'फ़िल्टर'},
    'apply': {'en': 'Apply', 'mr': 'लागू करा', 'hi': 'लागू करें'},
    'reset': {'en': 'Reset', 'mr': 'रीसेट', 'hi': 'रीसेट'},
    'view_all': {'en': 'View all', 'mr': 'सर्व पहा', 'hi': 'सब देखें'},
    'submit': {'en': 'Submit', 'mr': 'पाठवा', 'hi': 'भेजें'},
    'refresh': {'en': 'Refresh', 'mr': 'ताजे करा', 'hi': 'रीफ़्रेश'},
    'copy': {'en': 'Copy', 'mr': 'कॉपी', 'hi': 'कॉपी'},
    'copied': {'en': 'Copied', 'mr': 'कॉपी झाले', 'hi': 'कॉपी हो गया'},
    'unsaved': {
      'en': 'Removed from saved',
      'mr': 'जतन यादीतून काढले',
      'hi': 'सहेजी सूची से हटाया'
    },
    'saved': {'en': 'Saved', 'mr': 'जतन झाले', 'hi': 'सेव हो गया'},
    'optional': {'en': 'optional', 'mr': 'ऐच्छिक', 'hi': 'वैकल्पिक'},
    'all': {'en': 'All', 'mr': 'सर्व', 'hi': 'सभी'},
    'not_recorded': {
      'en': 'Not recorded',
      'mr': 'नोंद नाही',
      'hi': 'दर्ज नहीं'
    },
    'not_available': {
      'en': 'Not available',
      'mr': 'उपलब्ध नाही',
      'hi': 'उपलब्ध नहीं'
    },
    'yes': {'en': 'Yes', 'mr': 'होय', 'hi': 'हाँ'},
    'no': {'en': 'No', 'mr': 'नाही', 'hi': 'नहीं'},
    'demo_data': {'en': 'Demo data', 'mr': 'नमुना डेटा', 'hi': 'डेमो डेटा'},
    'observed': {'en': 'Observed', 'mr': 'निरीक्षित', 'hi': 'देखा गया'},
    'estimated': {'en': 'Estimated', 'mr': 'अंदाजित', 'hi': 'अनुमानित'},
    'offline_hint': {
      'en': 'Check that the phone can reach the backend.',
      'mr': 'फोन बॅकएंडपर्यंत पोहोचतो आहे का तपासा.',
      'hi': 'जाँचें कि फ़ोन बैकएंड तक पहुँच पा रहा है।',
    },
    // ----------------------------------------------------------------- auth
    'sign_in': {'en': 'Sign in', 'mr': 'प्रवेश करा', 'hi': 'साइन इन करें'},
    'sign_out': {'en': 'Sign out', 'mr': 'बाहेर पडा', 'hi': 'साइन आउट'},
    'sign_in_subtitle': {
      'en': 'Use your phone number or email',
      'mr': 'तुमचा मोबाइल क्रमांक किंवा ईमेल वापरा',
      'hi': 'अपना फ़ोन नंबर या ईमेल दें',
    },
    'phone_or_email': {
      'en': 'Phone or email',
      'mr': 'मोबाइल किंवा ईमेल',
      'hi': 'फ़ोन या ईमेल'
    },
    'phone_hint': {
      'en': 'In international format, e.g. +919000000001',
      'mr': 'आंतरराष्ट्रीय स्वरूपात, उदा. +919000000001',
      'hi': 'अंतर्राष्ट्रीय प्रारूप में, जैसे +919000000001',
    },
    'password': {'en': 'Password', 'mr': 'परवलीचा शब्द', 'hi': 'पासवर्ड'},
    'sign_in_with_otp': {
      'en': 'Sign in with OTP',
      'mr': 'OTP ने प्रवेश',
      'hi': 'OTP से साइन इन'
    },
    'sign_in_with_password': {
      'en': 'Use password instead',
      'mr': 'परवलीच्या शब्दाने प्रवेश',
      'hi': 'पासवर्ड से साइन इन',
    },
    'send_otp': {'en': 'Send OTP', 'mr': 'OTP पाठवा', 'hi': 'OTP भेजें'},
    'otp_code': {'en': 'OTP code', 'mr': 'OTP कोड', 'hi': 'OTP कोड'},
    'verify_and_sign_in': {
      'en': 'Verify and sign in',
      'mr': 'पडताळून प्रवेश करा',
      'hi': 'सत्यापित कर साइन इन'
    },
    'resend_otp': {
      'en': 'Resend OTP',
      'mr': 'पुन्हा OTP पाठवा',
      'hi': 'OTP फिर भेजें'
    },
    'otp_requested': {
      'en': 'OTP requested. It expires in',
      'mr': 'OTP मागवला. वैधता संपते',
      'hi': 'OTP भेजा गया। समय-सीमा',
    },
    'seconds': {'en': 'seconds', 'mr': 'सेकंद', 'hi': 'सेकंड'},
    'dev_otp_notice': {
      'en': 'Development OTP provider',
      'mr': 'विकास OTP प्रदाता',
      'hi': 'डेवलपमेंट OTP प्रदाता',
    },
    'dev_otp_explanation': {
      'en':
          'No SMS was sent. The backend is running the development OTP provider, which returns the code here so the flow can be tested. In production this code arrives by SMS only.',
      'mr':
          'कोणताही SMS पाठवला गेला नाही. बॅकएंड विकास OTP प्रदाता वापरत आहे, जो चाचणीसाठी कोड येथे दाखवतो. उत्पादनात हा कोड फक्त SMS ने मिळेल.',
      'hi':
          'कोई SMS नहीं भेजा गया। बैकएंड डेवलपमेंट OTP प्रदाता चला रहा है, जो परीक्षण के लिए कोड यहाँ दिखाता है। उत्पादन में यह कोड केवल SMS से आता है।',
    },
    'create_account': {
      'en': 'Create account',
      'mr': 'खाते तयार करा',
      'hi': 'खाता बनाएँ'
    },
    'full_name': {'en': 'Full name', 'mr': 'पूर्ण नाव', 'hi': 'पूरा नाम'},
    'email': {'en': 'Email', 'mr': 'ईमेल', 'hi': 'ईमेल'},
    'phone': {'en': 'Phone', 'mr': 'मोबाइल', 'hi': 'फ़ोन'},
    'no_account_yet': {'en': 'New here?', 'mr': 'नवीन आहात?', 'hi': 'नए हैं?'},
    'already_have_account': {
      'en': 'Already registered?',
      'mr': 'आधीच नोंदणी आहे?',
      'hi': 'पहले से पंजीकृत हैं?',
    },
    'forgot_password': {
      'en': 'Forgot password?',
      'mr': 'परवलीचा शब्द विसरला?',
      'hi': 'पासवर्ड भूल गए?'
    },
    'reset_password': {
      'en': 'Reset password',
      'mr': 'परवलीचा शब्द बदला',
      'hi': 'पासवर्ड रीसेट'
    },
    'demo_accounts': {
      'en': 'Demo accounts',
      'mr': 'नमुना खाती',
      'hi': 'डेमो खाते'
    },
    'demo_accounts_note': {
      'en':
          'Development data only. These accounts and their farms exist because the development seed script created them.',
      'mr':
          'फक्त विकास डेटा. ही खाती व शेतं विकास सीड स्क्रिप्टने तयार केली आहेत.',
      'hi':
          'केवल डेवलपमेंट डेटा। ये खाते और खेत डेवलपमेंट सीड स्क्रिप्ट से बने हैं।',
    },
    'use_this_account': {
      'en': 'Use this account',
      'mr': 'हे खाते वापरा',
      'hi': 'यह खाता उपयोग करें'
    },
    'session_expired': {
      'en': 'Your session expired. Please sign in again.',
      'mr': 'सत्र संपले. पुन्हा प्रवेश करा.',
      'hi': 'सत्र समाप्त हो गया। फिर साइन इन करें।',
    },
    'sign_in_required': {
      'en': 'Sign in to continue',
      'mr': 'पुढे जाण्यासाठी प्रवेश करा',
      'hi': 'जारी रखने के लिए साइन इन करें',
    },
    // ------------------------------------------------------------------ nav
    'nav_home': {'en': 'Home', 'mr': 'मुख्य', 'hi': 'होम'},
    'nav_farm': {'en': 'My farm', 'mr': 'माझे शेत', 'hi': 'मेरा खेत'},
    'nav_ai': {'en': 'AI tools', 'mr': 'AI साधने', 'hi': 'AI टूल'},
    'nav_community': {'en': 'Community', 'mr': 'समुदाय', 'hi': 'समुदाय'},
    'nav_more': {'en': 'More', 'mr': 'अधिक', 'hi': 'और'},
    'more_markets': {
      'en': 'Market prices',
      'mr': 'बाजार भाव',
      'hi': 'बाज़ार भाव'
    },
    'more_weather': {'en': 'Weather', 'mr': 'हवामान', 'hi': 'मौसम'},
    'more_schemes': {
      'en': 'Government schemes',
      'mr': 'सरकारी योजना',
      'hi': 'सरकारी योजनाएँ'
    },
    'more_notifications': {
      'en': 'Notifications',
      'mr': 'सूचना',
      'hi': 'सूचनाएँ'
    },
    'more_profile': {
      'en': 'Profile & settings',
      'mr': 'प्रोफाइल व सेटिंग',
      'hi': 'प्रोफ़ाइल व सेटिंग'
    },
    'more_search': {
      'en': 'Search everything',
      'mr': 'सर्वत्र शोध',
      'hi': 'सब कुछ खोजें'
    },
    'more_about': {
      'en': 'About this app',
      'mr': 'या अ‍ॅपविषयी',
      'hi': 'इस ऐप के बारे में'
    },
    'more_assistant': {
      'en': 'Ask a question',
      'mr': 'प्रश्न विचारा',
      'hi': 'प्रश्न पूछें'
    },
    'more_data_sources': {
      'en': 'Data sources',
      'mr': 'डेटा स्रोत',
      'hi': 'डेटा स्रोत'
    },
    // ----------------------------------------------------------------- home
    'dashboard_title': {'en': 'Home', 'mr': 'मुख्य पृष्ठ', 'hi': 'होम'},
    'welcome_back': {'en': 'Welcome', 'mr': 'स्वागत', 'hi': 'स्वागत'},
    'land_summary': {'en': 'Your land', 'mr': 'तुमची जमीन', 'hi': 'आपकी ज़मीन'},
    'total_farms': {'en': 'Farms', 'mr': 'शेतं', 'hi': 'खेत'},
    'total_area': {
      'en': 'Total area',
      'mr': 'एकूण क्षेत्र',
      'hi': 'कुल क्षेत्र'
    },
    'active_crops': {
      'en': 'Active crops',
      'mr': 'चालू पिके',
      'hi': 'चालू फ़सलें'
    },
    'harvested_crops': {
      'en': 'Harvested',
      'mr': 'काढणी झालेली',
      'hi': 'कटाई हो चुकी'
    },
    'crop_stage_counts': {
      'en': 'Crops by stage',
      'mr': 'अवस्थेनुसार पिके',
      'hi': 'अवस्था के अनुसार फ़सल'
    },
    'reminders': {'en': 'Reminders', 'mr': 'स्मरणपत्रे', 'hi': 'अनुस्मारक'},
    'no_reminders': {
      'en': 'No reminders right now.',
      'mr': 'सध्या स्मरणपत्र नाही.',
      'hi': 'अभी कोई अनुस्मारक नहीं।',
    },
    'data_freshness': {
      'en': 'Data freshness',
      'mr': 'डेटा ताजेपणा',
      'hi': 'डेटा की ताज़गी'
    },
    'profile_completeness': {
      'en': 'Profile completeness',
      'mr': 'प्रोफाइल पूर्णता',
      'hi': 'प्रोफ़ाइल पूर्णता'
    },
    'complete_profile': {
      'en': 'Complete your profile',
      'mr': 'प्रोफाइल पूर्ण करा',
      'hi': 'प्रोफ़ाइल पूरी करें'
    },
    'complete_profile_hint': {
      'en': 'More complete details give better scheme and advisory answers.',
      'mr': 'अधिक माहिती दिल्यास योजना व सल्ला अधिक अचूक मिळतो.',
      'hi': 'अधिक जानकारी से योजना और सलाह बेहतर मिलती है।',
    },
    'quick_actions': {
      'en': 'Quick actions',
      'mr': 'झटपट कामे',
      'hi': 'तुरंत काम'
    },
    'ask_ai': {
      'en': 'Ask the assistant',
      'mr': 'सहाय्यकाला विचारा',
      'hi': 'सहायक से पूछें'
    },
    'no_active_crops': {
      'en': 'No crop is recorded as growing yet.',
      'mr': 'अजून कोणतेही पीक वाढत असल्याची नोंद नाही.',
      'hi': 'अभी कोई फ़सल बढ़ती दर्ज नहीं है।',
    },
    // ----------------------------------------------------------------- farm
    'my_farms': {'en': 'My farms', 'mr': 'माझी शेतं', 'hi': 'मेरे खेत'},
    'add_farm': {'en': 'Add farm', 'mr': 'शेत जोडा', 'hi': 'खेत जोड़ें'},
    'farm_name': {'en': 'Farm name', 'mr': 'शेताचे नाव', 'hi': 'खेत का नाम'},
    'area': {'en': 'Area', 'mr': 'क्षेत्र', 'hi': 'क्षेत्र'},
    'area_unit': {'en': 'Unit', 'mr': 'एकक', 'hi': 'इकाई'},
    'village': {'en': 'Village', 'mr': 'गाव', 'hi': 'गाँव'},
    'taluka': {'en': 'Taluka', 'mr': 'तालुका', 'hi': 'तालुका'},
    'district': {'en': 'District', 'mr': 'जिल्हा', 'hi': 'ज़िला'},
    'state': {'en': 'State', 'mr': 'राज्य', 'hi': 'राज्य'},
    'pincode': {'en': 'PIN code', 'mr': 'पिन कोड', 'hi': 'पिन कोड'},
    'soil_type': {
      'en': 'Soil type',
      'mr': 'मातीचा प्रकार',
      'hi': 'मिट्टी का प्रकार'
    },
    'soil_ph': {
      'en': 'Soil pH',
      'mr': 'मातीचा सामू (pH)',
      'hi': 'मिट्टी का pH'
    },
    'irrigation': {'en': 'Irrigation', 'mr': 'पाणी व्यवस्था', 'hi': 'सिंचाई'},
    'ownership': {'en': 'Ownership', 'mr': 'मालकी', 'hi': 'स्वामित्व'},
    'location': {'en': 'Location', 'mr': 'ठिकाण', 'hi': 'स्थान'},
    'coordinates': {
      'en': 'Coordinates',
      'mr': 'निर्देशांक',
      'hi': 'निर्देशांक'
    },
    'notes': {'en': 'Notes', 'mr': 'टिपा', 'hi': 'टिप्पणी'},
    'no_farms': {
      'en': 'No farms added yet',
      'mr': 'अजून शेत जोडले नाही',
      'hi': 'अभी कोई खेत नहीं जोड़ा'
    },
    'no_farms_hint': {
      'en':
          'Add a farm to get weather for its location, crop tracking and AI recommendations.',
      'mr':
          'शेत जोडल्यावर त्याच्या ठिकाणचे हवामान, पीक नोंद व AI शिफारसी मिळतात.',
      'hi':
          'खेत जोड़ने पर उस स्थान का मौसम, फ़सल रिकॉर्ड और AI सुझाव मिलते हैं।',
    },
    'farm_details': {
      'en': 'Farm details',
      'mr': 'शेताची माहिती',
      'hi': 'खेत का विवरण'
    },
    'crops': {'en': 'Crops', 'mr': 'पिके', 'hi': 'फ़सलें'},
    'add_crop': {'en': 'Add crop', 'mr': 'पीक जोडा', 'hi': 'फ़सल जोड़ें'},
    'crop': {'en': 'Crop', 'mr': 'पीक', 'hi': 'फ़सल'},
    'variety': {'en': 'Variety', 'mr': 'जात', 'hi': 'किस्म'},
    'season': {'en': 'Season', 'mr': 'हंगाम', 'hi': 'मौसम'},
    'sowing_date': {
      'en': 'Sowing date',
      'mr': 'पेरणीची तारीख',
      'hi': 'बुवाई की तारीख'
    },
    'expected_harvest': {
      'en': 'Expected harvest',
      'mr': 'अपेक्षित काढणी',
      'hi': 'अपेक्षित कटाई'
    },
    'stage': {'en': 'Stage', 'mr': 'अवस्था', 'hi': 'अवस्था'},
    'status': {'en': 'Status', 'mr': 'स्थिती', 'hi': 'स्थिति'},
    'seed_source': {
      'en': 'Seed source',
      'mr': 'बियाणे स्रोत',
      'hi': 'बीज स्रोत'
    },
    'days_since_sowing': {
      'en': 'Days since sowing',
      'mr': 'पेरणीपासून दिवस',
      'hi': 'बुवाई से दिन'
    },
    'days_to_harvest': {
      'en': 'Days to harvest',
      'mr': 'काढणीस दिवस',
      'hi': 'कटाई तक दिन'
    },
    'soil_tests': {
      'en': 'Soil tests',
      'mr': 'माती परीक्षण',
      'hi': 'मिट्टी परीक्षण'
    },
    'add_soil_test': {
      'en': 'Add soil test',
      'mr': 'माती परीक्षण जोडा',
      'hi': 'मिट्टी परीक्षण जोड़ें'
    },
    'tested_on': {
      'en': 'Tested on',
      'mr': 'चाचणी तारीख',
      'hi': 'परीक्षण तारीख'
    },
    'nitrogen': {'en': 'Nitrogen', 'mr': 'नायट्रोजन', 'hi': 'नाइट्रोजन'},
    'phosphorus': {'en': 'Phosphorus', 'mr': 'फॉस्फरस', 'hi': 'फ़ॉस्फ़ोरस'},
    'potassium': {'en': 'Potassium', 'mr': 'पोटॅशियम', 'hi': 'पोटैशियम'},
    'organic_carbon': {
      'en': 'Organic carbon',
      'mr': 'सेंद्रिय कर्ब',
      'hi': 'जैविक कार्बन'
    },
    'lab_name': {
      'en': 'Lab name',
      'mr': 'प्रयोगशाळेचे नाव',
      'hi': 'प्रयोगशाला का नाम'
    },
    'latest_soil_test': {
      'en': 'Latest soil test',
      'mr': 'अलीकडील माती परीक्षण',
      'hi': 'नवीनतम मिट्टी परीक्षण'
    },
    'no_soil_test': {
      'en': 'No soil test recorded',
      'mr': 'माती परीक्षण नोंद नाही',
      'hi': 'कोई मिट्टी परीक्षण दर्ज नहीं'
    },
    'use_soil_test_values': {
      'en': 'Use these values in the crop recommendation',
      'mr': 'ही मूल्ये पीक शिफारसीत वापरा',
      'hi': 'इन मानों को फ़सल सुझाव में उपयोग करें',
    },
    'delete_farm_confirm': {
      'en':
          'Delete this farm? Its crops and soil tests are removed from your account.',
      'mr': 'हे शेत हटवायचे? त्याची पिके व माती परीक्षणे हटवली जातील.',
      'hi': 'यह खेत हटाएँ? इसकी फ़सलें और मिट्टी परीक्षण हट जाएँगे।',
    },
    'stage_guidance': {
      'en': 'Stage guidance',
      'mr': 'अवस्थेनुसार सल्ला',
      'hi': 'अवस्था अनुसार सलाह'
    },
    'add_event': {
      'en': 'Add field event',
      'mr': 'शेत नोंद जोडा',
      'hi': 'खेत गतिविधि जोड़ें'
    },
    'event_type': {
      'en': 'Event type',
      'mr': 'नोंदीचा प्रकार',
      'hi': 'गतिविधि प्रकार'
    },
    'occurred_on': {'en': 'Date', 'mr': 'तारीख', 'hi': 'तारीख'},
    // ------------------------------------------------------------------- ai
    'ai_tools': {'en': 'AI tools', 'mr': 'AI साधने', 'hi': 'AI टूल'},
    'ai_tools_intro': {
      'en':
          'These tools use the platform’s own models. Every result is AI-assisted — not a confirmed diagnosis or a guarantee.',
      'mr':
          'ही साधने प्लॅटफॉर्मची स्वतःची मॉडेल्स वापरतात. प्रत्येक निकाल AI-सहाय्यित आहे — खात्रीशीर निदान किंवा हमी नाही.',
      'hi':
          'ये टूल प्लेटफ़ॉर्म के अपने मॉडल उपयोग करते हैं। हर परिणाम AI-सहायित है — पक्का निदान या गारंटी नहीं।',
    },
    'crop_recommendation': {
      'en': 'Crop recommendation',
      'mr': 'पीक शिफारस',
      'hi': 'फ़सल सुझाव'
    },
    'crop_recommendation_hint': {
      'en':
          'Scores land from soil and weather values. They are relative model scores for ranking, not probabilities.',
      'mr':
          'माती व हवामान मूल्यांवरून पिकांचा क्रम ठरवला जातो. हे सापेक्ष मॉडेल गुण आहेत, संभाव्यता नाही.',
      'hi':
          'मिट्टी और मौसम मानों से फ़सलों का क्रम तय होता है। ये सापेक्ष मॉडल स्कोर हैं, संभावना नहीं।',
    },
    'disease_detection': {
      'en': 'Disease observation',
      'mr': 'रोग निरीक्षण',
      'hi': 'रोग अवलोकन'
    },
    'disease_detection_hint': {
      'en':
          'Compares a leaf photo with the classes the model was trained on. It cannot recognise anything outside those classes.',
      'mr':
          'पानाचा फोटो मॉडेलला शिकवलेल्या वर्गांशी तुलना करतो. त्या वर्गांबाहेरचे ते ओळखू शकत नाही.',
      'hi':
          'पत्ती की फ़ोटो को मॉडल के सीखे वर्गों से मिलाता है। उन वर्गों के बाहर कुछ नहीं पहचान सकता।',
    },
    'yield_prediction': {
      'en': 'Yield estimate',
      'mr': 'उत्पादन अंदाज',
      'hi': 'उपज अनुमान'
    },
    'yield_hint': {
      'en':
          'Estimates from the recorded crop, area and inputs. Treat it as a planning figure.',
      'mr': 'नोंदवलेले पीक, क्षेत्र व माहितीवरून अंदाज. नियोजनासाठी वापरा.',
      'hi':
          'दर्ज फ़सल, क्षेत्र और जानकारी से अनुमान। नियोजन के लिए उपयोग करें।',
    },
    'price_intelligence': {
      'en': 'Price outlook',
      'mr': 'भावाचा अंदाज',
      'hi': 'भाव का अनुमान'
    },
    'assistant': {'en': 'Assistant', 'mr': 'सहाय्यक', 'hi': 'सहायक'},
    'assistant_hint': {
      'en':
          'Answers come only from the platform’s own documents and posts. If nothing relevant is found, it says so instead of guessing.',
      'mr':
          'उत्तरे फक्त प्लॅटफॉर्मच्या दस्तऐवजांतून व पोस्टांतून दिली जातात. संबंधित काही न सापडल्यास अंदाज न लावता तसे सांगितले जाते.',
      'hi':
          'उत्तर केवल प्लेटफ़ॉर्म के दस्तावेज़ों और पोस्ट से आते हैं। कुछ न मिले तो अनुमान लगाने के बजाय स्पष्ट बताया जाता है।',
    },
    'ai_history': {
      'en': 'My AI requests',
      'mr': 'माझ्या AI विनंत्या',
      'hi': 'मेरे AI अनुरोध'
    },
    'ai_models': {
      'en': 'Models in use',
      'mr': 'वापरातील मॉडेल्स',
      'hi': 'उपयोग में मॉडल'
    },
    'not_a_diagnosis': {
      'en': 'Not a confirmed diagnosis',
      'mr': 'ही निश्चित निदान नाही',
      'hi': 'यह पुष्ट निदान नहीं है'
    },
    'ai_assisted': {
      'en': 'AI-assisted result',
      'mr': 'AI-सहाय्यित निकाल',
      'hi': 'AI-सहायित परिणाम'
    },
    'model_used': {'en': 'Model', 'mr': 'मॉडेल', 'hi': 'मॉडल'},
    'model_version': {'en': 'Version', 'mr': 'आवृत्ती', 'hi': 'संस्करण'},
    'score_type': {
      'en': 'Score type',
      'mr': 'गुणांचा प्रकार',
      'hi': 'स्कोर का प्रकार'
    },
    'inputs_used': {
      'en': 'Inputs used',
      'mr': 'वापरलेली माहिती',
      'hi': 'उपयोग किए इनपुट'
    },
    'input_sources': {
      'en': 'Where the inputs came from',
      'mr': 'माहितीचे स्रोत',
      'hi': 'इनपुट के स्रोत'
    },
    'limitations': {'en': 'Limitations', 'mr': 'मर्यादा', 'hi': 'सीमाएँ'},
    'warnings': {'en': 'Warnings', 'mr': 'इशारे', 'hi': 'चेतावनियाँ'},
    'upload_photo': {
      'en': 'Choose a photo',
      'mr': 'फोटो निवडा',
      'hi': 'फ़ोटो चुनें'
    },
    'take_photo': {'en': 'Take a photo', 'mr': 'फोटो काढा', 'hi': 'फ़ोटो लें'},
    'from_gallery': {'en': 'From gallery', 'mr': 'गॅलरीतून', 'hi': 'गैलरी से'},
    'analysing': {
      'en': 'Analysing…',
      'mr': 'विश्लेषण सुरू…',
      'hi': 'विश्लेषण हो रहा है…'
    },
    'predicted_labels': {
      'en': 'Model output',
      'mr': 'मॉडेलचे उत्तर',
      'hi': 'मॉडल आउटपुट'
    },
    'inconclusive': {
      'en': 'Inconclusive',
      'mr': 'निष्कर्ष नाही',
      'hi': 'निष्कर्ष नहीं'
    },
    'inconclusive_explanation': {
      'en':
          'The model did not reach a reliable answer for this photo. Please treat this as no result, not as a finding.',
      'mr':
          'या फोटोसाठी मॉडेल विश्वासार्ह उत्तर देऊ शकले नाही. हा निकाल नाही असेच समजा.',
      'hi':
          'इस फ़ोटो के लिए मॉडल भरोसेमंद उत्तर नहीं दे सका। इसे परिणाम न मानें।',
    },
    'confidence': {
      'en': 'Confidence',
      'mr': 'विश्वासार्हता',
      'hi': 'विश्वास स्तर'
    },
    'image_quality': {
      'en': 'Photo checks',
      'mr': 'फोटो तपासणी',
      'hi': 'फ़ोटो जाँच'
    },
    'trained_classes': {
      'en': 'Classes the model was trained on',
      'mr': 'मॉडेलला शिकवलेले वर्ग',
      'hi': 'मॉडल के सीखे वर्ग'
    },
    'recommendation': {
      'en': 'What to do next',
      'mr': 'पुढे काय करावे',
      'hi': 'आगे क्या करें'
    },
    'ask_question': {
      'en': 'Ask a question',
      'mr': 'प्रश्न विचारा',
      'hi': 'प्रश्न पूछें'
    },
    'question_hint': {
      'en': 'e.g. How much nitrogen for onion after transplanting?',
      'mr': 'उदा. कांद्याला लागवडीनंतर किती नायट्रोजन द्यावा?',
      'hi': 'जैसे प्याज़ में रोपाई के बाद कितना नाइट्रोजन दें?',
    },
    'sources': {'en': 'Sources', 'mr': 'स्रोत', 'hi': 'स्रोत'},
    'no_sources': {
      'en': 'No source was found for this question.',
      'mr': 'या प्रश्नासाठी स्रोत सापडला नाही.',
      'hi': 'इस प्रश्न के लिए कोई स्रोत नहीं मिला।',
    },
    'insufficient_evidence': {
      'en': 'Not enough evidence to answer',
      'mr': 'उत्तर देण्यासाठी पुरावा अपुरा',
      'hi': 'उत्तर देने के लिए पर्याप्त प्रमाण नहीं',
    },
    'ai_provider_disclosure': {
      'en': 'Provider',
      'mr': 'प्रदाता',
      'hi': 'प्रदाता'
    },
    'demo_provider': {
      'en': 'Demonstration provider',
      'mr': 'नमुना प्रदाता',
      'hi': 'प्रदर्शन प्रदाता'
    },
    'farm_context_used': {
      'en': 'Your farm details were used as context',
      'mr': 'तुमच्या शेताची माहिती संदर्भात वापरली',
      'hi': 'आपके खेत की जानकारी संदर्भ में उपयोग हुई',
    },
    'feedback_helpful': {
      'en': 'Correct and useful',
      'mr': 'बरोबर व उपयुक्त',
      'hi': 'सही और उपयोगी'
    },
    'feedback_not_helpful': {
      'en': 'Not useful',
      'mr': 'उपयुक्त नाही',
      'hi': 'उपयोगी नहीं'
    },
    'feedback_incorrect': {'en': 'Incorrect', 'mr': 'चुकीचे', 'hi': 'गलत'},
    'feedback_thanks': {
      'en': 'Thank you — your feedback was recorded.',
      'mr': 'धन्यवाद — तुमचा अभिप्राय नोंदवला गेला.',
      'hi': 'धन्यवाद — आपकी प्रतिक्रिया दर्ज हुई।',
    },
    'feedback_consent_note': {
      'en':
          'Training on your corrections happens only if you allow it in consent settings.',
      'mr':
          'तुमच्या दुरुस्त्या प्रशिक्षणासाठी वापरणे हे संमती सेटिंगमध्ये परवानगी दिल्यासच होते.',
      'hi':
          'आपके सुधार प्रशिक्षण में तभी उपयोग होते हैं जब आप सहमति सेटिंग में अनुमति दें।',
    },
    'delete_history_confirm': {
      'en': 'Remove this entry from your AI history?',
      'mr': 'ही नोंद AI इतिहासातून हटवायची?',
      'hi': 'इस प्रविष्टि को AI इतिहास से हटाएँ?',
    },
    'estimate_unavailable': {
      'en': 'No estimate available',
      'mr': 'अंदाज उपलब्ध नाही',
      'hi': 'कोई अनुमान उपलब्ध नहीं'
    },
    'age_days': {'en': 'Age (days)', 'mr': 'वय (दिवस)', 'hi': 'आयु (दिन)'},
    'grade_score': {'en': 'Score', 'mr': 'गुण', 'hi': 'स्कोर'},
    'request_id': {
      'en': 'Request id',
      'mr': 'विनंती क्रमांक',
      'hi': 'अनुरोध आईडी'
    },
    'latency': {
      'en': 'Response time',
      'mr': 'प्रतिसाद वेळ',
      'hi': 'प्रतिक्रिया समय'
    },
    'data_class': {'en': 'Data class', 'mr': 'डेटा वर्ग', 'hi': 'डेटा श्रेणी'},
    'how_it_was_produced': {
      'en': 'How this was produced',
      'mr': 'हे कसे तयार झाले',
      'hi': 'यह कैसे बना'
    },
    // ------------------------------------------------------------ community
    'community_feed': {'en': 'Community', 'mr': 'समुदाय', 'hi': 'समुदाय'},
    'create_post': {
      'en': 'Share something',
      'mr': 'काहीतरी शेअर करा',
      'hi': 'कुछ साझा करें'
    },
    'post_title': {'en': 'Title', 'mr': 'शीर्षक', 'hi': 'शीर्षक'},
    'post_body': {'en': 'Details', 'mr': 'तपशील', 'hi': 'विवरण'},
    'category': {'en': 'Category', 'mr': 'श्रेणी', 'hi': 'श्रेणी'},
    'language': {'en': 'Language', 'mr': 'भाषा', 'hi': 'भाषा'},
    'attach_photo': {
      'en': 'Attach a photo',
      'mr': 'फोटो जोडा',
      'hi': 'फ़ोटो जोड़ें'
    },
    'source_links': {
      'en': 'Source links',
      'mr': 'स्रोत दुवे',
      'hi': 'स्रोत लिंक'
    },
    'source_links_hint': {
      'en':
          'One URL per line. Official or institutional sources help others verify your point.',
      'mr':
          'एका ओळीत एक URL. अधिकृत किंवा संस्थात्मक स्रोत दिल्यास इतरांना पडताळता येते.',
      'hi':
          'प्रति पंक्ति एक URL. आधिकारिक या संस्थागत स्रोत से दूसरों को सत्यापन में मदद मिलती है।',
    },
    'publish': {'en': 'Publish', 'mr': 'प्रकाशित करा', 'hi': 'प्रकाशित करें'},
    'post_published': {
      'en': 'Posted',
      'mr': 'पोस्ट झाले',
      'hi': 'पोस्ट हो गया'
    },
    'reactions': {
      'en': 'Reactions',
      'mr': 'प्रतिक्रिया',
      'hi': 'प्रतिक्रियाएँ'
    },
    'comments': {'en': 'Comments', 'mr': 'प्रतिक्रिया-लेख', 'hi': 'टिप्पणियाँ'},
    'add_comment': {
      'en': 'Add a comment',
      'mr': 'प्रतिक्रिया लिहा',
      'hi': 'टिप्पणी जोड़ें'
    },
    'comment_hint': {
      'en': 'Write a comment…',
      'mr': 'प्रतिक्रिया लिहा…',
      'hi': 'टिप्पणी लिखें…'
    },
    'no_comments': {
      'en': 'No comments yet. Be the first to reply.',
      'mr': 'अजून प्रतिक्रिया नाही. पहिली प्रतिक्रिया तुम्ही द्या.',
      'hi': 'अभी कोई टिप्पणी नहीं। पहली टिप्पणी आप करें।',
    },
    'following_only': {
      'en': 'People I follow',
      'mr': 'मी अनुसरण करतो ते',
      'hi': 'जिन्हें फ़ॉलो करता हूँ'
    },
    'saved_only': {
      'en': 'Saved posts',
      'mr': 'जतन केलेल्या पोस्ट',
      'hi': 'सेव की गई पोस्ट'
    },
    'unanswered_only': {
      'en': 'Needs an answer',
      'mr': 'उत्तर हवे आहे',
      'hi': 'उत्तर चाहिए'
    },
    'sort_recent': {'en': 'Newest', 'mr': 'नवीन', 'hi': 'नवीनतम'},
    'sort_relevance': {
      'en': 'Most relevant',
      'mr': 'सर्वाधिक संबंधित',
      'hi': 'सर्वाधिक प्रासंगिक'
    },
    'report': {'en': 'Report', 'mr': 'तक्रार', 'hi': 'रिपोर्ट'},
    'report_reason': {'en': 'Reason', 'mr': 'कारण', 'hi': 'कारण'},
    'report_details': {'en': 'Details', 'mr': 'तपशील', 'hi': 'विवरण'},
    'report_submitted': {
      'en': 'Reported. A moderator will review it.',
      'mr': 'तक्रार नोंदवली. समन्वयक तपास करेल.',
      'hi': 'रिपोर्ट दर्ज हुई। एक मॉडरेटर समीक्षा करेगा।',
    },
    'report_already': {
      'en': 'You have already reported this.',
      'mr': 'तुम्ही याआधीच तक्रार केली आहे.',
      'hi': 'आप पहले ही रिपोर्ट कर चुके हैं।',
    },
    'trust_label': {
      'en': 'Information type',
      'mr': 'माहितीचा प्रकार',
      'hi': 'जानकारी का प्रकार'
    },
    'trust_reasons': {
      'en': 'Why this label',
      'mr': 'हा लेबल का',
      'hi': 'यह लेबल क्यों'
    },
    'ranking_method': {
      'en': 'Ordering method',
      'mr': 'क्रमवारी पद्धत',
      'hi': 'क्रम विधि'
    },
    'ranking_note': {
      'en':
          'Posts are ordered by recency, engagement and personalisation — not by correctness. Reactions are not proof that a claim is scientifically right.',
      'mr':
          'पोस्ट ताजेपणा, प्रतिक्रिया व वैयक्तिकरणानुसार क्रमवार लावल्या जातात — बरोबरीनुसार नाही. प्रतिक्रिया म्हणजे शास्त्रीय अचूकतेचा पुरावा नाही.',
      'hi':
          'पोस्ट ताज़गी, प्रतिक्रिया और वैयक्तिकरण से क्रम में लगती हैं — सत्यता से नहीं। प्रतिक्रियाएँ वैज्ञानिक सत्यता का प्रमाण नहीं हैं।',
    },
    'delete_post_confirm': {
      'en': 'Delete this post?',
      'mr': 'ही पोस्ट हटवायची?',
      'hi': 'यह पोस्ट हटाएँ?',
    },
    'no_posts': {
      'en': 'No posts to show',
      'mr': 'दाखवण्यासाठी पोस्ट नाही',
      'hi': 'दिखाने के लिए कोई पोस्ट नहीं'
    },
    'expert_verified': {
      'en': 'Verified expert',
      'mr': 'पडताळलेले तज्ज्ञ',
      'hi': 'सत्यापित विशेषज्ञ'
    },
    'follow': {'en': 'Follow', 'mr': 'अनुसरण', 'hi': 'फ़ॉलो'},
    'following': {'en': 'Following', 'mr': 'अनुसरत', 'hi': 'फ़ॉलो कर रहे'},
    'reaction_support': {'en': 'Support', 'mr': 'पाठिंबा', 'hi': 'समर्थन'},
    'reaction_helpful': {'en': 'Helpful', 'mr': 'उपयुक्त', 'hi': 'उपयोगी'},
    'reaction_insightful': {
      'en': 'Insightful',
      'mr': 'दृष्टी देणारे',
      'hi': 'जानकारीपूर्ण'
    },
    // ---------------------------------------------------------------- market
    'markets_title': {'en': 'Markets', 'mr': 'बाजार', 'hi': 'बाज़ार'},
    'prices': {'en': 'Prices', 'mr': 'भाव', 'hi': 'भाव'},
    'arrivals': {'en': 'Arrivals', 'mr': 'आवक', 'hi': 'आवक'},
    'mandi': {'en': 'Market', 'mr': 'बाजार समिती', 'hi': 'मंडी'},
    'modal_price': {'en': 'Modal price', 'mr': 'मोडल भाव', 'hi': 'मॉडल भाव'},
    'min_price': {'en': 'Minimum', 'mr': 'किमान', 'hi': 'न्यूनतम'},
    'max_price': {'en': 'Maximum', 'mr': 'कमाल', 'hi': 'अधिकतम'},
    'price_date': {'en': 'Date', 'mr': 'तारीख', 'hi': 'तारीख'},
    'arrivals_tonnes': {'en': 'Arrivals', 'mr': 'आवक', 'hi': 'आवक'},
    'source': {'en': 'Source', 'mr': 'स्रोत', 'hi': 'स्रोत'},
    'price_trend': {'en': 'Price trend', 'mr': 'भाव कल', 'hi': 'भाव रुझान'},
    'direction_rising': {'en': 'Rising', 'mr': 'वाढतोय', 'hi': 'बढ़ रहा'},
    'direction_falling': {'en': 'Falling', 'mr': 'घटतोय', 'hi': 'घट रहा'},
    'direction_stable': {'en': 'Stable', 'mr': 'स्थिर', 'hi': 'स्थिर'},
    'direction_unknown': {'en': 'Unknown', 'mr': 'माहित नाही', 'hi': 'अज्ञात'},
    'change_percent': {'en': 'Change', 'mr': 'बदल', 'hi': 'बदलाव'},
    'no_prices': {
      'en': 'No price rows for this selection.',
      'mr': 'या निवडीसाठी भाव नोंदी नाहीत.',
      'hi': 'इस चयन के लिए कोई भाव पंक्ति नहीं।',
    },
    'estimate_points_note': {
      'en':
          'Dotted points are model estimates; solid points are recorded prices.',
      'mr': 'ठिपके असलेले मुद्दे मॉडेल अंदाज आहेत; घट्ट मुद्दे नोंदवलेले भाव.',
      'hi': 'बिंदु वाले मान मॉडल अनुमान हैं; ठोस बिंदु दर्ज भाव।',
    },
    'horizon_days': {
      'en': 'Days ahead',
      'mr': 'पुढील दिवस',
      'hi': 'आगे के दिन'
    },
    'method_note': {'en': 'Method', 'mr': 'पद्धत', 'hi': 'विधि'},
    'market_provider': {
      'en': 'Price provider',
      'mr': 'भाव प्रदाता',
      'hi': 'भाव प्रदाता'
    },
    // --------------------------------------------------------------- weather
    'weather_title': {'en': 'Weather', 'mr': 'हवामान', 'hi': 'मौसम'},
    'current_weather': {'en': 'Right now', 'mr': 'आत्ता', 'hi': 'अभी'},
    'forecast': {'en': 'Forecast', 'mr': 'अंदाज', 'hi': 'पूर्वानुमान'},
    'temperature': {'en': 'Temperature', 'mr': 'तापमान', 'hi': 'तापमान'},
    'feels_like': {'en': 'Feels like', 'mr': 'जाणवते', 'hi': 'महसूस'},
    'humidity': {'en': 'Humidity', 'mr': 'आर्द्रता', 'hi': 'आर्द्रता'},
    'rainfall': {'en': 'Rainfall', 'mr': 'पाऊस', 'hi': 'वर्षा'},
    'rain_probability': {
      'en': 'Chance of rain',
      'mr': 'पावसाची शक्यता',
      'hi': 'बारिश की संभावना'
    },
    'wind': {'en': 'Wind', 'mr': 'वारा', 'hi': 'हवा'},
    'pressure': {'en': 'Pressure', 'mr': 'दाब', 'hi': 'दबाव'},
    'condition': {'en': 'Condition', 'mr': 'स्थिती', 'hi': 'स्थिति'},
    'observed_at': {'en': 'Observed', 'mr': 'निरीक्षण', 'hi': 'अवलोकन'},
    'advisories': {
      'en': 'Farming advisories',
      'mr': 'शेती सल्ले',
      'hi': 'खेती सलाह'
    },
    'alerts': {
      'en': 'Weather alerts',
      'mr': 'हवामान इशारे',
      'hi': 'मौसम चेतावनी'
    },
    'no_alerts': {
      'en': 'No active alerts.',
      'mr': 'सध्या इशारे नाहीत.',
      'hi': 'कोई सक्रिय चेतावनी नहीं।'
    },
    'weather_provider': {
      'en': 'Weather provider',
      'mr': 'हवामान प्रदाता',
      'hi': 'मौसम प्रदाता'
    },
    'use_farm_location': {
      'en': 'Use my farm location',
      'mr': 'माझ्या शेताचे ठिकाण वापरा',
      'hi': 'मेरे खेत का स्थान उपयोग करें'
    },
    'no_location_note': {
      'en': 'Add a farm with coordinates to get weather for that exact spot.',
      'mr': 'नेमके त्या ठिकाणचे हवामान हवे असल्यास निर्देशांकासह शेत जोडा.',
      'hi': 'उस स्थान का मौसम पाने के लिए निर्देशांक के साथ खेत जोड़ें।',
    },
    // --------------------------------------------------------------- schemes
    'schemes_title': {
      'en': 'Government schemes',
      'mr': 'सरकारी योजना',
      'hi': 'सरकारी योजनाएँ'
    },
    'scheme_details': {
      'en': 'Scheme details',
      'mr': 'योजनेची माहिती',
      'hi': 'योजना विवरण'
    },
    'benefits': {'en': 'Benefits', 'mr': 'फायदे', 'hi': 'लाभ'},
    'eligibility': {'en': 'Eligibility', 'mr': 'पात्रता', 'hi': 'पात्रता'},
    'application_process': {
      'en': 'How to apply',
      'mr': 'अर्ज कसा करावा',
      'hi': 'आवेदन कैसे करें'
    },
    'documents_required': {
      'en': 'Documents needed',
      'mr': 'आवश्यक कागदपत्रे',
      'hi': 'आवश्यक दस्तावेज़'
    },
    'official_source': {
      'en': 'Official source',
      'mr': 'अधिकृत स्रोत',
      'hi': 'आधिकारिक स्रोत'
    },
    'apply_at': {
      'en': 'Apply at',
      'mr': 'येथे अर्ज करा',
      'hi': 'यहाँ आवेदन करें'
    },
    'helpline': {'en': 'Helpline', 'mr': 'हेल्पलाइन', 'hi': 'हेल्पलाइन'},
    'last_verified': {
      'en': 'Last verified',
      'mr': 'शेवटची पडताळणी',
      'hi': 'अंतिम सत्यापन'
    },
    'verification_status': {
      'en': 'Verification',
      'mr': 'पडताळणी स्थिती',
      'hi': 'सत्यापन स्थिति'
    },
    'check_eligibility': {
      'en': 'Check eligibility',
      'mr': 'पात्रता तपासा',
      'hi': 'पात्रता जाँचें'
    },
    'eligibility_result': {
      'en': 'Eligibility result',
      'mr': 'पात्रता निकाल',
      'hi': 'पात्रता परिणाम'
    },
    'likely_eligible': {
      'en': 'Likely eligible',
      'mr': 'पात्र असण्याची शक्यता',
      'hi': 'संभवतः पात्र'
    },
    'likely_not_eligible': {
      'en': 'Likely not eligible',
      'mr': 'पात्र नसण्याची शक्यता',
      'hi': 'संभवतः अपात्र'
    },
    'needs_more_information': {
      'en': 'Needs more information',
      'mr': 'अधिक माहिती हवी',
      'hi': 'अधिक जानकारी चाहिए',
    },
    'missing_inputs': {
      'en': 'Information missing',
      'mr': 'अनुपलब्ध माहिती',
      'hi': 'अनुपलब्ध जानकारी'
    },
    'passed_rules': {
      'en': 'Conditions met',
      'mr': 'पूर्ण झालेल्या अटी',
      'hi': 'पूरी हुई शर्तें'
    },
    'failed_rules': {
      'en': 'Conditions not met',
      'mr': 'न पूर्ण झालेल्या अटी',
      'hi': 'पूरी न हुई शर्तें'
    },
    'unknown_rules': {
      'en': 'Cannot be checked yet',
      'mr': 'अजून तपासता येत नाही',
      'hi': 'अभी जाँच नहीं हो सकती'
    },
    'recommended_schemes': {
      'en': 'Schemes you may match',
      'mr': 'तुम्हाला लागू होऊ शकणाऱ्या योजना',
      'hi': 'आपसे मेल खा सकने वाली योजनाएँ'
    },
    'match_score': {'en': 'Rule match', 'mr': 'नियम जुळणी', 'hi': 'नियम मेल'},
    'rule_based_note': {
      'en':
          'Match percentages come from published rule conditions, not from a model, and are not a promise of approval.',
      'mr':
          'जुळणी टक्केवारी प्रकाशित अटींवर आधारित आहे, मॉडेलवर नाही, आणि मंजुरीची हमी नाही.',
      'hi':
          'मेल प्रतिशत प्रकाशित शर्तों पर आधारित है, मॉडल पर नहीं, और स्वीकृति की गारंटी नहीं।',
    },
    'has_kcc': {
      'en': 'Has Kisan Credit Card',
      'mr': 'किसान क्रेडिट कार्ड आहे',
      'hi': 'किसान क्रेडिट कार्ड है'
    },
    'annual_income': {
      'en': 'Annual income (₹)',
      'mr': 'वार्षिक उत्पन्न (₹)',
      'hi': 'वार्षिक आय (₹)'
    },
    'category_caste': {'en': 'Category', 'mr': 'प्रवर्ग', 'hi': 'वर्ग'},
    'tenant_farmer': {
      'en': 'Tenant farmer',
      'mr': 'भाडेकरू शेतकरी',
      'hi': 'किरायेदार किसान'
    },
    'eligibility_inputs_note': {
      'en':
          'Optional details improve the check. Anything you leave blank is reported as missing.',
      'mr':
          'ऐच्छिक माहिती दिल्यास तपासणी अधिक अचूक. रिकामे ठेवलेली माहिती “अनुपलब्ध” दाखवली जाते.',
      'hi':
          'वैकल्पिक जानकारी से जाँच बेहतर होती है। रिक्त छोड़ी गई जानकारी “अनुपलब्ध” दिखती है।',
    },
    'search_schemes': {
      'en': 'Search schemes',
      'mr': 'योजना शोधा',
      'hi': 'योजनाएँ खोजें'
    },
    'no_schemes': {
      'en': 'No schemes match this filter',
      'mr': 'या गाळणीशी जुळणारी योजना नाही',
      'hi': 'इस फ़िल्टर से कोई योजना नहीं'
    },
    // --------------------------------------------------------- notifications
    'notifications_title': {
      'en': 'Notifications',
      'mr': 'सूचना',
      'hi': 'सूचनाएँ'
    },
    'mark_all_read': {
      'en': 'Mark all read',
      'mr': 'सर्व वाचलेले करा',
      'hi': 'सभी पढ़ी हुई करें'
    },
    'unread': {'en': 'Unread', 'mr': 'न वाचलेले', 'hi': 'अपठित'},
    'no_notifications': {
      'en': 'No notifications',
      'mr': 'सूचना नाहीत',
      'hi': 'कोई सूचना नहीं'
    },
    'quiet_hours_start': {
      'en': 'Quiet hours',
      'mr': 'शांत वेळ',
      'hi': 'शांत समय'
    },
    'reason_timeout': {
      'en': 'the request timed out after 8 s',
      'mr': '८ सेकंदांनंतर विनंतीची वेळ संपली',
      'hi': '8 सेकंड बाद अनुरोध का समय समाप्त हो गया',
    },
    'reason_no_url': {
      'en': 'that is not an address the app can call',
      'mr': 'हे ॲप कॉल करू शकेल असा पत्ता नाही',
      'hi': 'यह ऐसा पता नहीं है जिसे ऐप कॉल कर सके',
    },
    'reason_no_answer': {
      'en': 'no HTTP response arrived',
      'mr': 'कोणताही HTTP प्रतिसाद आला नाही',
      'hi': 'कोई HTTP जवाब नहीं आया',
    },
    'advice_invalid': {
      'en': 'Type the address with its scheme and port, for example '
          'http://192.168.1.5:8000 — no path, no trailing slash.',
      'mr':
          'पत्ता स्कीम आणि पोर्टसह लिहा, उदा. http://192.168.1.5:8000 — मार्ग किंवा '
              'शेवटचा स्लॅश नको.',
      'hi':
          'पता स्कीम और पोर्ट के साथ लिखें, जैसे http://192.168.1.5:8000 — कोई पथ '
              'या अंतिम स्लैश नहीं.',
    },
    'advice_timeout': {
      'en': 'Nothing answered within 8 seconds, which means the request was '
          'dropped rather than refused — usually a firewall, or a router that '
          'keeps wireless clients apart.',
      'mr': '८ सेकंदांत काहीच उत्तर दिले नाही, म्हणजे विनंती नाकारली नाही तर टाकून दिली '
          'गेली — सामान्यतः फायरवॉल, किंवा वायरलेस क्लायंट वेगळे ठेवणारा राउटर.',
      'hi': '8 सेकंड में कोई जवाब नहीं आया, यानी अनुरोध अस्वीकार नहीं हुआ बल्कि छोड़ '
          'दिया गया — आमतौर पर फ़ायरवॉल, या वायरलेस क्लाइंट अलग रखने वाला राउटर.',
    },
    'advice_refused': {
      'en': 'The device was reached but the port is closed, so nothing is '
          'listening there: start the API with --host 0.0.0.0 --port 8000.',
      'mr':
          'उपकरण गाठले पण पोर्ट बंद आहे, तिथे काही ऐकत नाही: API --host 0.0.0.0 '
              '--port 8000 ने सुरू करा.',
      'hi':
          'डिवाइस तक पहुँच गया पर पोर्ट बंद है, वहाँ कुछ सुन नहीं रहा: API को '
              '--host 0.0.0.0 --port 8000 के साथ शुरू करें.',
    },
    'advice_unreachable': {
      'en': 'Nothing answered on that address and port.',
      'mr': 'त्या पत्त्यावर आणि पोर्टवर काहीच उत्तर दिले नाही.',
      'hi': 'उस पते और पोर्ट पर कुछ भी जवाब नहीं दिया.',
    },
    'advice_network': {
      'en': 'This phone is on {local}; the address typed is on {target}. If the '
          'two differ, this device is not on the backend\'s network — connect it '
          'to the same Wi-Fi (not a guest network) and try again.',
      'mr': 'हा फोन {local} वर आहे; टाकलेला पत्ता {target} वर आहे. दोन्ही वेगळे असल्यास '
          'हे उपकरण बॅकएंडच्या नेटवर्कवर नाही — त्याच वाय-फायवर (गेस्ट नेटवर्क नको) जोडा '
          'आणि पुन्हा प्रयत्न करा.',
      'hi': 'यह फ़ोन {local} पर है; डाला गया पता {target} पर है. दोनों अलग हों तो यह '
          'डिवाइस बैकएंड के नेटवर्क पर नहीं है — उसी वाय-फ़ाई (गेस्ट नेटवर्क नहीं) से '
          'जोड़ें और फिर कोशिश करें.',
    },
    'advice_same_network': {
      'en': 'This phone is on the same network as that address, so the network is '
          'not the obstacle — the backend or the firewall on its machine is next.',
      'mr':
          'हा फोन त्या पत्त्याच्याच नेटवर्कवर आहे, त्यामुळे अडथळा नेटवर्क नाही — पुढे '
              'बॅकएंड किंवा त्याच्या संगणकावरील फायरवॉल तपासा.',
      'hi':
          'यह फ़ोन उसी पते के नेटवर्क पर है, इसलिए रुकावट नेटवर्क नहीं है — आगे बैकएंड या '
              'उसके कंप्यूटर का फ़ायरवॉल देखें.',
    },
    'advice_firewall': {
      'en':
          'On the machine running the backend, allow inbound TCP on that port '
              '(and check that a VPN on the phone is not taking the route).',
      'mr':
          'बॅकएंड चालवणाऱ्या संगणकावर त्या पोर्टवर इनबाउंड TCP परवानगी द्या (आणि '
              'फोनवरील VPN मार्ग घेत नाही ना ते तपासा).',
      'hi':
          'बैकएंड चलाने वाले कंप्यूटर पर उस पोर्ट पर इनबाउंड TCP की अनुमति दें (और '
              'देखें कि फ़ोन का VPN रास्ता नहीं ले रहा).',
    },
    'advice_help': {
      'en': 'If the same address works in a browser on the phone, the backend is '
          'fine and the app is not the problem. docs/mobile_release.md §4c has the '
          'full checklist.',
      'mr':
          'फोनच्या ब्राउझरमध्ये तोच पत्ता चालत असेल, तर बॅकएंड ठीक आहे आणि अडचण ॲपमध्ये '
              'नाही. संपूर्ण तपासणी docs/mobile_release.md §4c मध्ये आहे.',
      'hi':
          'फ़ोन के ब्राउज़र में वही पता चले तो बैकएंड ठीक है और समस्या ऐप में नहीं है. '
              'पूरी जाँच सूची docs/mobile_release.md §4c में है.',
    },
    'advice_check': {
      'en':
          'Put {path} (and /ready) in the phone browser at the same address: an '
              'answer there is the proof the network is not the problem.',
      'mr':
          'त्याच पत्त्यावर फोनच्या ब्राउझरमध्ये {path} (आणि /ready) उघडा: तिथे उत्तर '
              'आले तर नेटवर्क अडचण नाही याचा पुरावा मिळेल.',
      'hi':
          'उसी पते पर फ़ोन के ब्राउज़र में {path} (और /ready) खोलें: वहाँ जवाब मिलना '
              'ही प्रमाण है कि नेटवर्क समस्या नहीं है.',
    },
    'server_invalid': {
      'en': 'That address was not saved. Use http://<host>:<port>, for example '
          'http://192.168.1.5:8000. A host on the public internet must be given as '
          'https://.',
      'mr': 'तो पत्ता जतन झाला नाही. http://<host>:<port> वापरा, उदा. '
          'http://192.168.1.5:8000. इंटरनेटवरील होस्ट https:// असाच द्यावा.',
      'hi': 'वह पता सेव नहीं हुआ. http://<host>:<port> इस्तेमाल करें, जैसे '
          'http://192.168.1.5:8000. इंटरनेट पर का होस्ट https:// ही दें.',
    },
    'server_saved': {
      'en': 'Saved as',
      'mr': 'जतन केलेले पत्ते',
      'hi': 'सेव किया गया',
    },
    'server_settings': {
      'en': 'Backend server',
      'mr': 'बॅकएंड सर्व्हर',
      'hi': 'बैकएंड सर्वर',
    },
    'server_address': {
      'en': 'Backend address',
      'mr': 'बॅकएंड पत्ता',
      'hi': 'बैकएंड पता',
    },
    'server_help': {
      'en': 'The app talks to a Digital Village backend. If it cannot connect, check that the '
          'backend is running, that it was started with --host 0.0.0.0, and that this device '
          'is on the same network.',
      'mr': 'हे ॲप डिजिटल व्हिलेज बॅकएंडशी जोडते. जोडणी होत नसेल तर बॅकएंड सुरू आहे का, ते '
          '--host 0.0.0.0 ने सुरू केले आहे का, आणि हे उपकरण त्याच नेटवर्कवर आहे का ते तपासा.',
      'hi': 'यह ऐप डिजिटल विलेज बैकएंड से जुड़ता है. कनेक्शन न हो तो देखें कि बैकएंड चल रहा है, '
          'वह --host 0.0.0.0 के साथ शुरू हुआ है, और यह डिवाइस उसी नेटवर्क पर है.',
    },
    'server_examples': {
      'en': 'Emulator: http://10.0.2.2:8000 · Phone: http://<your PC IP>:8000',
      'mr':
          'एम्युलेटर: http://10.0.2.2:8000 · फोन: http://<तुमच्या PC चा IP>:8000',
      'hi': 'एमुलेटर: http://10.0.2.2:8000 · फ़ोन: http://<आपके PC का IP>:8000',
    },
    'change': {'en': 'Change', 'mr': 'बदला', 'hi': 'बदलें'},
    'check_connection_saves': {
      'en':
          'The address is saved first, then the app really calls /health and /ready on it.',
      'mr':
          'पत्ता आधी जतन होतो, नंतर ॲप खरोखर त्यावर /health आणि /ready ला कॉल करते.',
      'hi':
          'पता पहले सेव होता है, फिर ऐप सचमुच उस पर /health और /ready को कॉल करता है.',
    },
    'check_connection': {
      'en': 'Test connection',
      'mr': 'जोडणी तपासा',
      'hi': 'कनेक्शन जाँचें',
    },
    'connection_reachable': {
      'en': 'Reachable',
      'mr': 'प्रतिसाद मिळाला',
      'hi': 'पहुँच गया'
    },
    'connection_not_ready': {
      'en': 'Reachable, but not ready',
      'mr': 'प्रतिसाद मिळाला, पण तयार नाही',
      'hi': 'पहुँच गया, पर तैयार नहीं',
    },
    'connection_unreachable': {
      'en': 'No answer',
      'mr': 'कोणताही प्रतिसाद नाही',
      'hi': 'कोई जवाब नहीं'
    },
    'network_error_hint': {
      'en':
          'Tap the server address above to point the app at your backend and test it.',
      'mr':
          'वरील सर्व्हर पत्त्यावर टॅप करून ॲपला तुमच्या बॅकएंडकडे वळवा आणि तपासा.',
      'hi':
          'ऊपर दिए सर्वर पते पर टैप करके ऐप को अपने बैकएंड की ओर इंगित करें और जाँचें.',
    },
    'after_connecting': {
      'en': 'Then sign in',
      'mr': 'नंतर साइन इन करा',
      'hi': 'फिर साइन इन करें'
    },
    'sign_in_hint': {
      'en':
          'Once /health answers, sign in with your phone number or the demo account below.',
      'mr':
          '/health ने प्रतिसाद दिल्यावर तुमच्या फोन क्रमांकाने किंवा खालील डेमो खात्याने साइन इन करा.',
      'hi':
          '/health का जवाब आने पर अपने फ़ोन नंबर या नीचे दिए डेमो खाते से साइन इन करें.',
    },
    'notification_preferences': {
      'en': 'Notification settings',
      'mr': 'सूचना सेटिंग',
      'hi': 'सूचना सेटिंग'
    },
    'pref_in_app': {
      'en': 'In-app notifications',
      'mr': 'अ‍ॅपमधील सूचना',
      'hi': 'ऐप में सूचनाएँ'
    },
    'pref_push': {
      'en': 'Push notifications',
      'mr': 'पुश सूचना',
      'hi': 'पुश सूचनाएँ'
    },
    'pref_weather': {
      'en': 'Weather alerts',
      'mr': 'हवामान इशारे',
      'hi': 'मौसम चेतावनी'
    },
    'pref_market': {
      'en': 'Market price updates',
      'mr': 'बाजार भाव अपडेट',
      'hi': 'बाज़ार भाव अपडेट'
    },
    'pref_crop': {
      'en': 'Crop reminders',
      'mr': 'पीक स्मरणपत्रे',
      'hi': 'फ़सल अनुस्मारक'
    },
    'pref_community': {
      'en': 'Community activity',
      'mr': 'समुदाय हालचाल',
      'hi': 'समुदाय गतिविधि'
    },
    'pref_schemes': {
      'en': 'Scheme updates',
      'mr': 'योजना अपडेट',
      'hi': 'योजना अपडेट'
    },
    'pref_ai': {
      'en': 'AI job updates',
      'mr': 'AI काम अपडेट',
      'hi': 'AI कार्य अपडेट'
    },
    'pref_digest_only': {
      'en': 'Digest only',
      'mr': 'फक्त सारांश',
      'hi': 'केवल सारांश'
    },
    'max_per_day': {
      'en': 'Maximum per day',
      'mr': 'दररोज कमाल',
      'hi': 'प्रतिदिन अधिकतम'
    },
    'push_note': {
      'en':
          'Push delivery requires a configured push provider and a device token. Until then, notifications are shown in the app only.',
      'mr':
          'पुश वितरणासाठी प्रदाता व डिव्हाइस टोकन आवश्यक. तोपर्यंत सूचना फक्त अ‍ॅपमध्ये दिसतील.',
      'hi':
          'पुश डिलीवरी के लिए प्रदाता और डिवाइस टोकन ज़रूरी है। तब तक सूचनाएँ केवल ऐप में दिखेंगी।',
    },
    // --------------------------------------------------------------- profile
    'profile_title': {
      'en': 'Profile & settings',
      'mr': 'प्रोफाइल व सेटिंग',
      'hi': 'प्रोफ़ाइल व सेटिंग'
    },
    'edit_profile': {
      'en': 'Edit profile',
      'mr': 'प्रोफाइल बदला',
      'hi': 'प्रोफ़ाइल बदलें'
    },
    'display_name': {
      'en': 'Display name',
      'mr': 'दाखवले जाणारे नाव',
      'hi': 'प्रदर्शित नाम'
    },
    'primary_crops': {
      'en': 'Main crops',
      'mr': 'मुख्य पिके',
      'hi': 'मुख्य फ़सलें'
    },
    'interests': {'en': 'Interests', 'mr': 'आवडी', 'hi': 'रुचियाँ'},
    'experience_years': {
      'en': 'Farming experience (years)',
      'mr': 'शेती अनुभव (वर्षे)',
      'hi': 'खेती अनुभव (वर्ष)'
    },
    'total_land': {'en': 'Total land', 'mr': 'एकूण जमीन', 'hi': 'कुल ज़मीन'},
    'bio': {'en': 'About me', 'mr': 'माझ्याविषयी', 'hi': 'मेरे बारे में'},
    'organisation': {'en': 'Organisation', 'mr': 'संस्था', 'hi': 'संस्था'},
    'public_profile': {
      'en': 'Show my profile to the community',
      'mr': 'माझे प्रोफाइल समुदायाला दाखवा',
      'hi': 'मेरी प्रोफ़ाइल समुदाय को दिखाएँ'
    },
    'account': {'en': 'Account', 'mr': 'खाते', 'hi': 'खाता'},
    'verified': {'en': 'Verified', 'mr': 'पडताळलेले', 'hi': 'सत्यापित'},
    'not_verified': {
      'en': 'Not verified',
      'mr': 'पडताळलेले नाही',
      'hi': 'सत्यापित नहीं'
    },
    'member_since': {'en': 'Member since', 'mr': 'सदस्य', 'hi': 'सदस्य'},
    'consents_title': {
      'en': 'Consent settings',
      'mr': 'संमती सेटिंग',
      'hi': 'सहमति सेटिंग'
    },
    'consent_required': {'en': 'Required', 'mr': 'आवश्यक', 'hi': 'आवश्यक'},
    'policy_version': {
      'en': 'Policy version',
      'mr': 'धोरण आवृत्ती',
      'hi': 'नीति संस्करण'
    },
    'data_export': {
      'en': 'Download my data',
      'mr': 'माझा डेटा मिळवा',
      'hi': 'मेरा डेटा डाउनलोड'
    },
    'data_export_note': {
      'en':
          'Requests a copy of your account data. The backend prepares the export; this app only requests it.',
      'mr':
          'तुमच्या खात्याच्या डेटाची प्रत मागवते. निर्यात बॅकएंड तयार करते; हे अ‍ॅप फक्त विनंती करते.',
      'hi':
          'आपके खाते डेटा की प्रति का अनुरोध करता है। निर्यात बैकएंड बनाता है; यह ऐप केवल अनुरोध करता है।',
    },
    'export_failed': {
      'en': 'Could not request the export:',
      'mr': 'निर्यात मागणी करता आली नाही:',
      'hi': 'निर्यात अनुरोध नहीं हो सका:'
    },
    'export_requested': {
      'en': 'Export requested. You will be notified when it is ready.',
      'mr': 'निर्यात मागवली. तयार झाल्यावर सूचना मिळेल.',
      'hi': 'निर्यात अनुरोध दर्ज। तैयार होने पर सूचना मिलेगी।',
    },
    'delete_account': {
      'en': 'Delete my account',
      'mr': 'माझे खाते हटवा',
      'hi': 'मेरा खाता हटाएँ'
    },
    'delete_account_note': {
      'en': 'Removes the account from the platform. This cannot be undone.',
      'mr': 'हे खाते प्लॅटफॉर्मवरून हटते. हे पुन्हा मिळवता येणार नाही.',
      'hi': 'यह खाता प्लेटफ़ॉर्म से हट जाता है। इसे वापस नहीं लाया जा सकता।',
    },
    'api_base_url': {
      'en': 'Backend address',
      'mr': 'बॅकएंड पत्ता',
      'hi': 'बैकएंड पता'
    },
    'api_base_url_note': {
      'en':
          'Needed only for testing on a physical phone, which cannot reach the emulator address. A production build must use an HTTPS address.',
      'mr':
          'फक्त खऱ्या फोनवर चाचणी करताना लागते, कारण तो एम्युलेटरचा पत्ता गाठू शकत नाही. उत्पादनात HTTPS पत्ता वापरावा.',
      'hi':
          'केवल असली फ़ोन पर परीक्षण के लिए ज़रूरी, क्योंकि वह एम्युलेटर पता नहीं पा सकता। उत्पादन में HTTPS पता उपयोग करें।',
    },
    'reset_default': {
      'en': 'Reset to default',
      'mr': 'डिफॉल्टवर आणा',
      'hi': 'डिफ़ॉल्ट पर लाएँ'
    },
    'developer_options': {'en': 'Advanced', 'mr': 'प्रगत', 'hi': 'उन्नत'},
    'about_app': {'en': 'About', 'mr': 'अ‍ॅपविषयी', 'hi': 'ऐप के बारे में'},
    'about_body': {
      'en':
          'Digital Village is a farmer platform for farm records, community knowledge, market prices, weather, government schemes and AI-assisted tools. Every result in the app is labelled with where it came from.',
      'mr':
          'डिजिटल व्हिलेज हे शेत नोंदी, समुदाय माहिती, बाजार भाव, हवामान, सरकारी योजना व AI-सहाय्यित साधनांसाठीचे व्यासपीठ आहे. अ‍ॅपमधील प्रत्येक निकाल त्याचा स्रोत दाखवतो.',
      'hi':
          'डिजिटल विलेज खेत रिकॉर्ड, समुदाय ज्ञान, बाज़ार भाव, मौसम, सरकारी योजनाएँ और AI-सहायित टूल के लिए प्लेटफ़ॉर्म है। ऐप का हर परिणाम अपने स्रोत के साथ दिखता है।',
    },
    'limitations_title': {
      'en': 'Known limitations',
      'mr': 'माहीत मर्यादा',
      'hi': 'ज्ञात सीमाएँ'
    },
    'limitations_body': {
      'en':
          'Weather, market prices and the language model run on configured providers. When a demonstration provider is active the app says so on the screen that uses it. AI outputs are assisted results, not confirmed diagnoses, and they do not replace an agricultural officer or veterinarian.',
      'mr':
          'हवामान, बाजार भाव व भाषा मॉडेल नेमून दिलेल्या प्रदात्यांवर चालतात. नमुना प्रदाता सुरू असल्यास संबंधित स्क्रीनवर तसे दिसते. AI निकाल सहाय्यित आहेत, खात्रीशीर निदान नाही, आणि ते कृषी अधिकारी किंवा पशुवैद्याची जागा घेत नाहीत.',
      'hi':
          'मौसम, बाज़ार भाव और भाषा मॉडल तय किए गए प्रदाताओं पर चलते हैं। प्रदर्शन प्रदाता सक्रिय हो तो संबंधित स्क्रीन पर लिखा होता है। AI परिणाम सहायित हैं, पक्का निदान नहीं, और कृषि अधिकारी या पशु चिकित्सक की जगह नहीं लेते।',
    },
    'privacy_policy': {
      'en': 'Privacy policy',
      'mr': 'गोपनीयता धोरण',
      'hi': 'गोपनीयता नीति'
    },
    'terms_of_service': {
      'en': 'Terms of service',
      'mr': 'सेवा अटी',
      'hi': 'सेवा शर्तें'
    },
    'policy_placeholder': {
      'en':
          'Placeholder — the legal text must be published at a stable URL before the app is released.',
      'mr':
          'जागा राखीव — अ‍ॅप प्रकाशित करण्यापूर्वी कायदेशीर मजकूर स्थिर URL वर प्रकाशित करणे आवश्यक.',
      'hi':
          'प्लेसहोल्डर — ऐप जारी करने से पहले कानूनी पाठ स्थिर URL पर प्रकाशित करना आवश्यक।',
    },
    'version_label': {'en': 'Version', 'mr': 'आवृत्ती', 'hi': 'संस्करण'},
    // ---------------------------------------------------------------- search
    'search_everything': {
      'en': 'Search everything',
      'mr': 'सर्वत्र शोध',
      'hi': 'सब कुछ खोजें'
    },
    'search_hint': {
      'en': 'Search crops, diseases, schemes, posts and prices',
      'mr': 'पिके, रोग, योजना, पोस्ट व भाव शोधा',
      'hi': 'फ़सल, रोग, योजनाएँ, पोस्ट और भाव खोजें',
    },
    'results_count': {'en': 'results', 'mr': 'निकाल', 'hi': 'परिणाम'},
    'no_results': {
      'en': 'No results',
      'mr': 'निकाल नाही',
      'hi': 'कोई परिणाम नहीं'
    },
    'search_mode': {'en': 'Search mode', 'mr': 'शोध पद्धत', 'hi': 'खोज मोड'},
    'semantic_note': {
      'en':
          'Semantic search compares meaning, so loosely related items can appear. The method used is shown with the results.',
      'mr':
          'अर्थाधारित शोध अर्थाची तुलना करतो, त्यामुळे सैल संबंध असलेले निकालही दिसू शकतात. वापरलेली पद्धत निकालांसोबत दाखवली जाते.',
      'hi':
          'अर्थ-आधारित खोज अर्थ की तुलना करती है, इसलिए कम संबंधित परिणाम भी दिख सकते हैं। उपयोग की गई विधि परिणामों के साथ दिखती है।',
    },
    'suggestions': {'en': 'Suggestions', 'mr': 'सूचना', 'hi': 'सुझाव'},
  };
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  bool isSupported(Locale locale) => AppLocalizations.supportedLocales
      .any((supported) => supported.languageCode == locale.languageCode);

  @override
  Future<AppLocalizations> load(Locale locale) async =>
      AppLocalizations(locale);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

/// Shorthand used throughout the screens: `s.t('save')`.
extension AppLocalizationsX on BuildContext {
  AppLocalizations get s => AppLocalizations.of(this);

  String t(String key) => AppLocalizations.of(this).t(key);

  /// [t] with `{name}` placeholders filled in (addresses, ports, counts).
  String tf(String key, Map<String, String> values) =>
      AppLocalizations.of(this).tf(key, values);
}
