import 'package:digital_village_app/models/ai.dart';
import 'package:digital_village_app/models/farm.dart';
import 'package:digital_village_app/models/markets.dart';
import 'package:digital_village_app/models/notifications.dart';
import 'package:digital_village_app/models/schemes.dart';
import 'package:digital_village_app/models/weather.dart';
import 'package:flutter_test/flutter_test.dart';

/// The payloads below mirror the real API responses (shapes taken from the
/// running backend's OpenAPI schema and live captures). They exist so a renamed
/// backend field fails a test rather than silently rendering an empty screen.
void main() {
  group('paged envelope', () {
    test('parses items and paging metadata', () {
      final page = SchemePage.fromJson({
        'items': [
          {'slug': 'pm-kisan', 'name': 'PM-KISAN'},
        ],
        'page': 1,
        'page_size': 20,
        'total': 41,
        'total_pages': 3,
        'has_next': true,
      });
      expect(page.items, hasLength(1));
      expect(page.items.first.name, 'PM-KISAN');
      expect(page.total, 41);
      expect(page.hasNext, isTrue);
    });
  });

  group('farm', () {
    test('keeps hectares separate from the farmer-entered unit', () {
      final farm = Farm.fromJson({
        'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'name': 'Wada plot',
        'area_value': 2.5,
        'area_unit': 'acre',
        'area_hectares': 1.0117,
        'soil_type': 'black',
        'irrigation_type': 'drip',
        'village': 'Ozar',
        'district': 'Nashik',
        'state': 'Maharashtra',
        'latitude': 19.9975,
        'longitude': 73.7898,
        'soil_ph': 7.4,
      });
      expect(farm.name, 'Wada plot');
      expect(farm.areaValue, 2.5);
      expect(farm.areaUnit, 'acre');
      expect(farm.areaHectares, closeTo(1.0117, 0.0001));
      expect(farm.soilPh, 7.4);
      expect(farm.placeLabel, contains('Ozar'));
      expect(farm.placeLabel, contains('Nashik'));
    });

    test('a farm without a name still parses (never a null crash)', () {
      final farm =
          Farm.fromJson({'id': 'b', 'area_value': 1, 'area_unit': 'acre'});
      expect(farm.name, isNotEmpty);
      expect(farm.latitude, isNull);
    });
  });

  group('crop recommendation', () {
    test('a relative score stays a score, and the demo dataset is flagged', () {
      final result = CropRecommendation.fromJson({
        'model_name': 'crop_recommendation',
        'model_version': 'v202610051518',
        'score_type': 'relative_model_score',
        'score_type_note':
            'Scores are relative model outputs, not calibrated probabilities.',
        'confidence_interpretation': 'The top crop leads by a clear margin.',
        'ranked': [
          {
            'crop_code': 'onion',
            'name_en': 'Onion',
            'name_mr': 'कांदा',
            'rank': 1,
            'score': 0.8123,
            'score_display': 0.8123,
            'envelope_note': 'Suitable for black soil.',
          },
          {
            'crop_code': 'tomato',
            'name_en': 'Tomato',
            'rank': 2,
            'score': 0.6211
          },
        ],
        'inputs_used': {'soil_ph': 7.4, 'rainfall_mm': 600},
        'input_sources': {'soil_ph': 'farm'},
        'warnings': ['Rainfall was estimated from the district average.'],
        'limitations': ['Trained on a public sample dataset.'],
        'disclaimer': 'AI-assisted result — not a confirmed recommendation.',
        'is_demo_dataset': true,
        'data_class': 'model_output',
        'request_id': 'req-1',
      });
      expect(result.ranked.first.cropCode, 'onion');
      expect(result.ranked.first.localizedName('mr'), 'कांदा');
      expect(result.ranked.first.localizedName('en'), 'Onion');
      expect(result.scoreType, 'relative_model_score');
      expect(result.isDemoDataset, isTrue);
      expect(result.disclaimer, contains('AI-assisted'));
      expect(result.warnings, hasLength(1));
    });
  });

  group('disease detection — the three non-answer states', () {
    test('quality gate failure lists the failing checks', () {
      final observation = DiseaseObservation.fromJson({
        'model_name': 'leaf_disease',
        'model_version': 'v1',
        'predictions': [],
        'model_trained_classes': ['early_blight', 'healthy'],
        'confidence_interpretation': 'Image quality was too poor to score.',
        'inconclusive': false,
        'quality_gate_failed': true,
        'image_quality': [
          {'name': 'blur', 'passed': false, 'detail': 'Image is too blurry.'},
          {'name': 'lighting', 'passed': true},
        ],
        'recommendation':
            'Retake the photo in daylight, filling the frame with one leaf.',
        'recommendation_kind': 'retake_photo',
        'disclaimer': 'AI-assisted result — not a confirmed diagnosis.',
        'crop_supported': true,
        'related_knowledge': [],
        'similar_posts': [],
      });
      expect(observation.qualityGateFailed, isTrue);
      expect(observation.imageQuality.first.passed, isFalse);
      expect(observation.predictions, isEmpty);
    });

    test('an unsupported crop is reported as unsupported, not scored', () {
      final observation = DiseaseObservation.fromJson({
        'model_name': 'leaf_disease',
        'model_version': 'v1',
        'predictions': [],
        'model_trained_classes': ['early_blight'],
        'confidence_interpretation': 'This crop is not covered by the model.',
        'inconclusive': false,
        'quality_gate_failed': false,
        'image_quality': [],
        'recommendation': 'Consult your local Krishi Vigyan Kendra.',
        'disclaimer': 'AI-assisted result — not a confirmed diagnosis.',
        'crop_supported': false,
        'crop_coverage_note': 'The model was not trained on banana.',
      });
      expect(observation.cropSupported, isFalse);
      expect(observation.cropCoverageNote, contains('banana'));
    });

    test('a scored observation keeps raw scores and the trained classes', () {
      final observation = DiseaseObservation.fromJson({
        'model_name': 'leaf_disease',
        'model_version': 'v1',
        'predictions': [
          {
            'label': 'early_blight',
            'display_name': 'Early blight',
            'score': 0.71,
            'is_healthy': false
          },
          {
            'label': 'healthy',
            'display_name': 'Healthy',
            'score': 0.21,
            'is_healthy': true
          },
        ],
        'model_trained_classes': ['early_blight', 'healthy'],
        'confidence_interpretation': 'Weak evidence.',
        'inconclusive': true,
        'quality_gate_failed': false,
        'image_quality': [
          {'name': 'blur', 'passed': true},
        ],
        'recommendation': 'Monitor for two days before spraying.',
        'disclaimer': 'AI-assisted result — not a confirmed diagnosis.',
        'score_type': 'softmax',
        'confidence': 0.71,
        'crop_supported': true,
      });
      expect(observation.inconclusive, isTrue);
      expect(observation.predictions.first.score, 0.71);
      expect(observation.modelTrainedClasses, contains('healthy'));
    });
  });

  group('assistant answer', () {
    test('insufficient evidence is carried through with its reason', () {
      final answer = AssistantAnswer.fromJson({
        'answer': 'I could not find anything in the knowledge base about this.',
        'citations': [],
        'insufficient_evidence': true,
        'insufficient_reason':
            'No document scored above the minimum relevance.',
        'notices': ['Answers are generated from platform documents only.'],
        'disclaimer':
            'AI-assisted answer — verify with your local agriculture officer.',
        'llm': {'provider': 'mock', 'model': 'demo-llm', 'is_demo': true},
        'retrieval': {
          'method': 'pgvector_cosine',
          'embedding_provider': 'mock',
          'embedding_is_demo': true,
        },
        'guardrails': {
          'grounded': false,
          'flags': ['no_evidence'],
          'answer_modified': false
        },
        'data_class': 'model_output',
        'ai_request_id': 'req-9',
      });
      expect(answer.insufficientEvidence, isTrue);
      expect(answer.citations, isEmpty);
      expect(answer.llmIsDemo, isTrue);
      expect(answer.embeddingIsDemo, isTrue);
      expect(answer.guardrailFlags, contains('no_evidence'));
      expect(answer.grounded, isFalse);
      expect(answer.aiRequestId, 'req-9');
    });

    test('citations keep the source document reference', () {
      final answer = AssistantAnswer.fromJson({
        'answer': 'Apply potassium sulphate as per the package label. [1]',
        'citations': [
          {
            'kind': 'knowledge_chunk',
            'ref_id': 'chunk-1',
            'title': 'Onion nutrient management',
            'source_name': 'Maharashtra agriculture department',
            'source_url': 'https://example.org/onion',
            'score': 0.8123,
            'verification_status': 'official',
          },
        ],
        'insufficient_evidence': false,
        'notices': [],
        'disclaimer': 'AI-assisted answer.',
        'llm': {'provider': 'openai', 'model': 'gpt-x', 'is_demo': false},
        'retrieval': {
          'method': 'pgvector_cosine',
          'embedding_provider': 'openai'
        },
        'guardrails': {'grounded': true, 'flags': [], 'answer_modified': false},
      });
      expect(answer.grounded, isTrue);
      expect(answer.citations.single.refId, 'chunk-1');
      expect(answer.citations.single.sourceUrl, 'https://example.org/onion');
    });
  });

  group('weather', () {
    test('demo provider values are flagged, never silently shown as live', () {
      final now = WeatherNow.fromJson({
        'latitude': 19.99,
        'longitude': 73.79,
        'provider': 'mock',
        'temperature_c': 31.4,
        'feels_like_c': 34.0,
        'humidity_percent': 62,
        'rainfall_mm': 0.0,
        'wind_speed_kmh': 12.6,
        'condition_code': 'partly_cloudy',
        'condition_text': 'Partly cloudy',
        'observed_at': '2026-10-06T04:30:00Z',
        'is_demo': true,
        'demo_notice': 'Synthetic weather values for development.',
        'data_class': 'demo',
      });
      expect(now.isDemo, isTrue);
      expect(now.demoNotice, isNotNull);
      expect(now.temperatureC, 31.4);
      expect(now.observedAt, isNotNull);
    });

    test('forecast advisories carry their data class', () {
      final forecast = WeatherForecast.fromJson({
        'provider': 'mock',
        'is_demo': true,
        'advisories': ['Delay irrigation: rain expected in 48 hours.'],
        'advisories_data_class': 'model_output',
        'days': [
          {
            'forecast_for': '2026-10-07',
            'temp_min_c': 21.0,
            'temp_max_c': 33.5,
            'rainfall_probability_percent': 60,
            'condition_code': 'rain',
          },
        ],
      });
      expect(forecast.days.single.rainfallProbabilityPercent, 60);
      expect(forecast.advisoriesDataClass, 'model_output');
      expect(forecast.isDemo, isTrue);
    });
  });

  group('markets', () {
    test('an estimate row is marked as an estimate', () {
      final price = MarketPrice.fromJson({
        'market_code': 'nashik',
        'market_name': 'Nashik (Lasalgaon)',
        'crop_code': 'onion',
        'crop_name': 'Onion',
        'district': 'Nashik',
        'price_date': '2026-10-05',
        'min_price': 1800,
        'max_price': 2450,
        'modal_price': 2200,
        'unit': 'quintal',
        'arrivals_tonnes': 112.5,
        'source': 'mock',
        'is_estimate': true,
      });
      expect(price.modalPrice, 2200);
      expect(price.isEstimate, isTrue);
      expect(price.unit, 'quintal');
      expect(price.arrivalsTonnes, 112.5);
    });
  });

  group('schemes', () {
    test('scheme keeps its official source and verification status', () {
      final scheme = Scheme.fromJson({
        'slug': 'pm-kisan',
        'name': 'PM-KISAN',
        'description': 'Income support for landholding farmers.',
        'category': 'income_support',
        'level': 'central',
        'official_source_name': 'PM-KISAN portal',
        'official_source_url': 'https://pmkisan.gov.in',
        'verification_status': 'official',
        'documents_required': ['Aadhaar', 'Land records'],
        'state_codes': ['MH'],
        'is_demo': false,
        'last_verified_on': '2026-09-01',
      });
      expect(scheme.officialSourceUrl, 'https://pmkisan.gov.in');
      expect(scheme.verificationStatus, 'official');
      expect(scheme.isDemo, isFalse);
      expect(scheme.lastVerifiedOn, isNotNull);
    });

    test('eligibility separates passed, failed and unknown rules', () {
      final result = EligibilityResult.fromJson({
        'scheme_slug': 'pm-kisan',
        'scheme_name': 'PM-KISAN',
        'status': 'needs_more_information',
        'confidence': 'partial',
        'passed': [
          {
            'field': 'has_kcc',
            'message': 'You hold a Kisan Credit Card.',
            'expected': 'true'
          },
        ],
        'failed': [
          {
            'field': 'land_size',
            'message': 'Land holding above the limit.',
            'expected': '<= 2 ha'
          },
        ],
        'unknown': [
          {'field': 'income', 'message': 'Annual income was not provided.'},
        ],
        'missing_inputs': ['annual_income_inr'],
        'configuration_warnings': [
          'Rule text needs review by a scheme expert.'
        ],
        'explanation': 'Two of three rules could be evaluated.',
        'official_source_name': 'PM-KISAN portal',
        'official_source_url': 'https://pmkisan.gov.in',
        'verification_status': 'official',
        'disclaimer': 'This is an automated check, not an approval decision.',
        'last_verified_on': '2026-09-01',
      });
      expect(result.status, 'needs_more_information');
      expect(result.unknown.single.field, 'income');
      expect(result.missingInputs, contains('annual_income_inr'));
      expect(result.disclaimer, contains('not an approval'));
    });
  });

  group('notifications', () {
    test('unread count and read flag survive parsing', () {
      final page = NotificationPage.fromJson({
        'items': [
          {
            'id': '11111111-2222-3333-4444-555555555555',
            'type': 'weather_alert',
            'title': 'Heavy rain expected',
            'body': 'Delay spraying for 48 hours.',
            'language': 'en',
            'read': false,
            'subject_type': 'weather_alert',
            'subject_id': 'alert-1',
            'deep_link': '/weather',
            'created_at': '2026-10-06T04:00:00Z',
          },
        ],
        'page': 1,
        'page_size': 20,
        'total': 1,
        'total_pages': 1,
        'has_next': false,
        'unread_count': 1,
      });
      expect(page.unreadCount, 1);
      expect(page.items.single.read, isFalse);
      expect(page.items.single.deepLink, '/weather');
    });
  });
}
