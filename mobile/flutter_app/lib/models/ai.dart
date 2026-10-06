import 'json_utils.dart';

/// One ranked crop from `POST /ai/crop-recommendation`.
///
/// `score` is whatever `score_type` says it is. With the shipping model that is
/// `relative_model_score` — a ranking value, **not** a probability — and the app
/// prints `scoreTypeNote` next to the numbers so nobody reads them as "75 %
/// chance of a good harvest".
class RankedCrop {
  const RankedCrop({
    required this.cropCode,
    required this.nameEn,
    required this.rank,
    required this.score,
    required this.scoreDisplay,
    required this.envelopeNote,
    this.nameMr,
    this.nameHi,
    this.typicalEnvelope,
  });

  factory RankedCrop.fromJson(Map<String, dynamic> json) => RankedCrop(
        cropCode: asString(json['crop_code']),
        nameEn:
            asString(json['name_en'], fallback: asString(json['crop_code'])),
        rank: asInt(json['rank']),
        score: asDouble(json['score']),
        scoreDisplay:
            asDouble(json['score_display'], fallback: asDouble(json['score'])),
        envelopeNote: asString(json['envelope_note']),
        nameMr: asStringOrNull(json['name_mr']),
        nameHi: asStringOrNull(json['name_hi']),
        typicalEnvelope: json['typical_envelope'] == null
            ? null
            : asMap(json['typical_envelope']),
      );

  final String cropCode;
  final String nameEn;
  final int rank;
  final double score;
  final double scoreDisplay;
  final String envelopeNote;
  final String? nameMr;
  final String? nameHi;
  final Map<String, dynamic>? typicalEnvelope;

  String localizedName(String languageCode) => switch (languageCode) {
        'mr' => nameMr ?? nameEn,
        'hi' => nameHi ?? nameEn,
        _ => nameEn,
      };
}

/// `POST /ai/crop-recommendation` response.
class CropRecommendation {
  const CropRecommendation({
    required this.modelName,
    required this.modelVersion,
    required this.scoreType,
    required this.scoreTypeNote,
    required this.confidenceInterpretation,
    required this.ranked,
    required this.inputsUsed,
    required this.inputSources,
    required this.warnings,
    required this.limitations,
    required this.disclaimer,
    this.inputUnits = const {},
    this.topMargin,
    this.isDemoDataset = false,
    this.dataClass,
    this.latencyMs,
    this.requestId,
  });

  factory CropRecommendation.fromJson(Map<String, dynamic> json) =>
      CropRecommendation(
        modelName: asString(json['model_name']),
        modelVersion: asString(json['model_version']),
        scoreType: asString(json['score_type']),
        scoreTypeNote: asString(json['score_type_note']),
        confidenceInterpretation: asString(json['confidence_interpretation']),
        ranked: asMapList(json['ranked']).map(RankedCrop.fromJson).toList(),
        inputsUsed: asMap(json['inputs_used']),
        inputSources: asMap(json['input_sources']),
        warnings: asStringList(json['warnings']),
        limitations: asStringList(json['limitations']),
        disclaimer: asString(json['disclaimer']),
        inputUnits: asMap(json['input_units']),
        topMargin: asDoubleOrNull(json['top_margin']),
        isDemoDataset: asBool(json['is_demo_dataset']),
        dataClass: asStringOrNull(json['data_class']),
        latencyMs: asIntOrNull(json['latency_ms']),
        requestId: asStringOrNull(json['request_id']),
      );

  final String modelName;
  final String modelVersion;
  final String scoreType;
  final String scoreTypeNote;
  final String confidenceInterpretation;
  final List<RankedCrop> ranked;
  final Map<String, dynamic> inputsUsed;
  final Map<String, dynamic> inputSources;
  final List<String> warnings;
  final List<String> limitations;
  final String disclaimer;
  final Map<String, dynamic> inputUnits;
  final double? topMargin;
  final bool isDemoDataset;
  final String? dataClass;
  final int? latencyMs;
  final String? requestId;

  bool get scoreIsProbability => scoreType.contains('probability');
}

/// One candidate class from the disease model.
class DiseasePrediction {
  const DiseasePrediction({
    required this.label,
    required this.displayName,
    required this.score,
    this.isHealthy = false,
    this.isInconclusive = false,
  });

  factory DiseasePrediction.fromJson(Map<String, dynamic> json) =>
      DiseasePrediction(
        label: asString(json['label']),
        displayName:
            asString(json['display_name'], fallback: asString(json['label'])),
        score: asDouble(json['score']),
        isHealthy: asBool(json['is_healthy']),
        isInconclusive: asBool(json['is_inconclusive']),
      );

  final String label;
  final String displayName;
  final double score;
  final bool isHealthy;
  final bool isInconclusive;
}

class ImageQualityCheck {
  const ImageQualityCheck(
      {required this.name, required this.passed, this.detail});

  factory ImageQualityCheck.fromJson(Map<String, dynamic> json) =>
      ImageQualityCheck(
        name: asString(json['name']),
        passed: asBool(json['passed']),
        detail: asStringOrNull(json['detail']),
      );

  final String name;
  final bool passed;
  final String? detail;
}

/// `POST /ai/disease-detection`. Always presented as an AI-assisted observation,
/// never as a diagnosis; `inconclusive` and `qualityGateFailed` are first-class
/// states the screen must handle.
class DiseaseObservation {
  const DiseaseObservation({
    required this.modelName,
    required this.modelVersion,
    required this.predictions,
    required this.modelTrainedClasses,
    required this.confidenceInterpretation,
    required this.inconclusive,
    required this.qualityGateFailed,
    required this.imageQuality,
    required this.recommendation,
    required this.disclaimer,
    this.scoreType,
    this.confidence,
    this.cropCoverageNote,
    this.recommendationKind = 'advisory',
    this.cropCode,
    this.cropSupported = true,
    this.relatedKnowledge = const [],
    this.similarPosts = const [],
    this.dataClass,
    this.latencyMs,
    this.requestId,
    this.mediaId,
  });

  factory DiseaseObservation.fromJson(Map<String, dynamic> json) =>
      DiseaseObservation(
        modelName: asString(json['model_name']),
        modelVersion: asString(json['model_version']),
        predictions: asMapList(json['predictions'])
            .map(DiseasePrediction.fromJson)
            .toList(),
        modelTrainedClasses: asStringList(json['model_trained_classes']),
        confidenceInterpretation: asString(json['confidence_interpretation']),
        inconclusive: asBool(json['inconclusive']),
        qualityGateFailed: asBool(json['quality_gate_failed']),
        imageQuality: asMapList(json['image_quality'])
            .map(ImageQualityCheck.fromJson)
            .toList(),
        recommendation: asString(json['recommendation']),
        disclaimer: asString(json['disclaimer']),
        scoreType: asStringOrNull(json['score_type']),
        confidence: asDoubleOrNull(json['confidence']),
        cropCoverageNote: asStringOrNull(json['crop_coverage_note']),
        recommendationKind:
            asString(json['recommendation_kind'], fallback: 'advisory'),
        cropCode: asStringOrNull(json['crop_code']),
        cropSupported: asBool(json['crop_supported'], fallback: true),
        relatedKnowledge: asMapList(json['related_knowledge']),
        similarPosts: asMapList(json['similar_community_posts']),
        dataClass: asStringOrNull(json['data_class']),
        latencyMs: asIntOrNull(json['latency_ms']),
        requestId: asStringOrNull(json['request_id']),
        mediaId: asStringOrNull(json['media_id']),
      );

  final String modelName;
  final String modelVersion;
  final List<DiseasePrediction> predictions;
  final List<String> modelTrainedClasses;
  final String confidenceInterpretation;
  final bool inconclusive;
  final bool qualityGateFailed;
  final List<ImageQualityCheck> imageQuality;
  final String recommendation;
  final String disclaimer;
  final String? scoreType;
  final double? confidence;
  final String? cropCoverageNote;
  final String recommendationKind;
  final String? cropCode;
  final bool cropSupported;
  final List<Map<String, dynamic>> relatedKnowledge;
  final List<Map<String, dynamic>> similarPosts;
  final String? dataClass;
  final int? latencyMs;
  final String? requestId;
  final String? mediaId;
}

/// `POST /ai/yield-prediction`.
class YieldPrediction {
  const YieldPrediction({
    required this.modelName,
    required this.modelVersion,
    required this.cropCode,
    required this.unit,
    required this.estimate,
    required this.rangeBasis,
    required this.inputsUsed,
    required this.scoreType,
    required this.confidenceInterpretation,
    required this.limitations,
    required this.disclaimer,
    this.range,
    this.dataClass,
    this.latencyMs,
    this.requestId,
  });

  factory YieldPrediction.fromJson(Map<String, dynamic> json) =>
      YieldPrediction(
        modelName: asString(json['model_name']),
        modelVersion: asString(json['model_version']),
        cropCode: asString(json['crop_code']),
        unit: asString(json['unit']),
        estimate: asDouble(json['estimate']),
        rangeBasis: asString(json['range_basis']),
        inputsUsed: asMap(json['inputs_used']),
        scoreType: asString(json['score_type']),
        confidenceInterpretation: asString(json['confidence_interpretation']),
        limitations: asStringList(json['limitations']),
        disclaimer: asString(json['disclaimer']),
        range: json['range'] == null ? null : asMap(json['range']),
        dataClass: asStringOrNull(json['data_class']),
        latencyMs: asIntOrNull(json['latency_ms']),
        requestId: asStringOrNull(json['request_id']),
      );

  final String modelName;
  final String modelVersion;
  final String cropCode;
  final String unit;
  final double estimate;
  final String rangeBasis;
  final Map<String, dynamic> inputsUsed;
  final String scoreType;
  final String confidenceInterpretation;
  final List<String> limitations;
  final String disclaimer;
  final Map<String, dynamic>? range;
  final String? dataClass;
  final int? latencyMs;
  final String? requestId;
}

/// An item of the assistant's source list (`citations` of `POST /knowledge/ask`).
class EvidenceItem {
  const EvidenceItem({
    required this.kind,
    required this.refId,
    required this.title,
    this.sourceName,
    this.sourceUrl,
    this.snippet,
    this.score,
    this.publishedAt,
    this.verificationStatus,
  });

  factory EvidenceItem.fromJson(Map<String, dynamic> json) => EvidenceItem(
        kind: asString(json['kind']),
        refId: asString(json['ref_id']),
        title: asString(json['title']),
        sourceName: asStringOrNull(json['source_name']),
        sourceUrl: asStringOrNull(json['source_url']),
        snippet: asStringOrNull(json['snippet']),
        score: asDoubleOrNull(json['score']),
        publishedAt: asDateTimeOrNull(json['published_at']),
        verificationStatus: asStringOrNull(json['verification_status']),
      );

  final String kind;
  final String refId;
  final String title;
  final String? sourceName;
  final String? sourceUrl;
  final String? snippet;
  final double? score;
  final DateTime? publishedAt;
  final String? verificationStatus;
}

/// `POST /knowledge/ask` — the RAG assistant's answer.
///
/// `insufficientEvidence` is deliberately rendered prominently: when the corpus
/// has nothing relevant, the app must show the warning state rather than let an
/// extractive demo answer look like knowledge.
class AssistantAnswer {
  const AssistantAnswer({
    required this.answer,
    required this.citations,
    required this.insufficientEvidence,
    required this.notices,
    required this.disclaimer,
    required this.grounded,
    this.insufficientReason,
    this.llmProvider,
    this.llmModel,
    this.llmIsDemo = false,
    this.llmNote,
    this.retrievalMethod,
    this.embeddingProvider,
    this.embeddingIsDemo = false,
    this.sourceTypes = const [],
    this.dataClass,
    this.aiRequestId,
    this.guardrailFlags = const [],
    this.answerModified = false,
  });

  factory AssistantAnswer.fromJson(Map<String, dynamic> json) {
    final llm = asMap(json['llm']);
    final retrieval = asMap(json['retrieval']);
    final guardrails = asMap(json['guardrails']);
    return AssistantAnswer(
      answer: asString(json['answer']),
      citations:
          asMapList(json['citations']).map(EvidenceItem.fromJson).toList(),
      insufficientEvidence: asBool(json['insufficient_evidence']),
      notices: asStringList(json['notices']),
      disclaimer: asString(json['disclaimer']),
      grounded: asBool(guardrails['grounded']),
      insufficientReason: asStringOrNull(json['insufficient_reason']),
      llmProvider: asStringOrNull(llm['provider']),
      llmModel: asStringOrNull(llm['model']),
      llmIsDemo: asBool(llm['is_demo']),
      llmNote: asStringOrNull(llm['note']),
      retrievalMethod: asStringOrNull(retrieval['method']),
      embeddingProvider: asStringOrNull(retrieval['embedding_provider']),
      embeddingIsDemo: asBool(retrieval['embedding_is_demo']),
      sourceTypes: asStringList(json['source_types']),
      dataClass: asStringOrNull(json['data_class']),
      aiRequestId: asStringOrNull(json['ai_request_id']),
      guardrailFlags: asStringList(guardrails['flags']),
      answerModified: asBool(guardrails['answer_modified']),
    );
  }

  final String answer;
  final List<EvidenceItem> citations;
  final bool insufficientEvidence;
  final List<String> notices;
  final String disclaimer;
  final bool grounded;
  final String? insufficientReason;
  final String? llmProvider;
  final String? llmModel;
  final bool llmIsDemo;
  final String? llmNote;
  final String? retrievalMethod;
  final String? embeddingProvider;
  final bool embeddingIsDemo;
  final List<String> sourceTypes;
  final String? dataClass;
  final String? aiRequestId;
  final List<String> guardrailFlags;
  final bool answerModified;
}

/// One entry of the model registry (`GET /ai/models`).
class ModelCard {
  const ModelCard({
    required this.name,
    required this.version,
    required this.stage,
    required this.isActive,
    required this.installedOnDisk,
    this.displayName,
    this.task,
    this.framework,
    this.metrics = const {},
    this.trainingData = const {},
    this.trainedAt,
    this.notes,
    this.modelCardUrl,
  });

  factory ModelCard.fromJson(Map<String, dynamic> json) => ModelCard(
        name: asString(json['name']),
        version: asString(json['version']),
        stage: asString(json['stage'], fallback: 'unknown'),
        isActive: asBool(json['is_active']),
        installedOnDisk: asBool(json['installed_on_disk']),
        displayName: asStringOrNull(json['display_name']),
        task: asStringOrNull(json['task']),
        framework: asStringOrNull(json['framework']),
        metrics: asMap(json['metrics']),
        trainingData: asMap(json['training_data']),
        trainedAt: asDateTimeOrNull(json['trained_at']),
        notes: asStringOrNull(json['notes']),
        modelCardUrl: asStringOrNull(json['model_card_url']),
      );

  final String name;
  final String version;
  final String stage;
  final bool isActive;
  final bool installedOnDisk;
  final String? displayName;
  final String? task;
  final String? framework;
  final Map<String, dynamic> metrics;
  final Map<String, dynamic> trainingData;
  final DateTime? trainedAt;
  final String? notes;
  final String? modelCardUrl;

  /// Validation metrics that the API actually reported, flattened for display.
  Map<String, dynamic> get validationMetrics => asMap(metrics['validation']);
  Map<String, dynamic> get testMetrics => asMap(metrics['test']);
}

class ModelRegistry {
  const ModelRegistry({
    required this.models,
    required this.artifactsDir,
    this.registryNote,
  });

  factory ModelRegistry.fromJson(Map<String, dynamic> json) => ModelRegistry(
        models: asMapList(json['models']).map(ModelCard.fromJson).toList(),
        artifactsDir: asString(json['artifacts_dir']),
        registryNote: asStringOrNull(json['registry_note']),
      );

  final List<ModelCard> models;
  final String artifactsDir;
  final String? registryNote;
}

/// An uploaded image (`POST /media/upload`).
class MediaAsset {
  const MediaAsset({
    required this.id,
    required this.purpose,
    required this.storageBackend,
    required this.mimeType,
    required this.sizeBytes,
    this.publicUrl,
    this.width,
    this.height,
    this.checksumSha256,
    this.validationNotes = const [],
  });

  factory MediaAsset.fromJson(Map<String, dynamic> json) => MediaAsset(
        id: requiredId(json['id'], 'media asset'),
        purpose: asString(json['purpose']),
        storageBackend: asString(json['storage_backend']),
        mimeType: asString(json['mime_type']),
        sizeBytes: asInt(json['size_bytes']),
        publicUrl: asStringOrNull(json['public_url']),
        width: asIntOrNull(json['width']),
        height: asIntOrNull(json['height']),
        checksumSha256: asStringOrNull(json['checksum_sha256']),
        validationNotes: asStringList(json['validation_notes']),
      );

  final String id;
  final String purpose;
  final String storageBackend;
  final String mimeType;
  final int sizeBytes;
  final String? publicUrl;
  final int? width;
  final int? height;
  final String? checksumSha256;
  final List<String> validationNotes;
}

/// One AI request from `GET /ai/history`.
class AiHistoryEntry {
  const AiHistoryEntry({
    required this.id,
    required this.kind,
    required this.createdAt,
    this.modelName,
    this.modelVersion,
    this.summary,
    this.dataClass,
    this.cropCode,
    this.feedbackVerdict,
  });

  factory AiHistoryEntry.fromJson(Map<String, dynamic> json) => AiHistoryEntry(
        id: requiredId(json['id'], 'AI request'),
        kind: asString(json['kind'], fallback: 'unknown'),
        createdAt: asDateTime(json['created_at']),
        modelName: asStringOrNull(json['model_name']),
        modelVersion: asStringOrNull(json['model_version']),
        summary: asStringOrNull(json['summary']),
        dataClass: asStringOrNull(json['data_class']),
        cropCode: asStringOrNull(json['crop_code']),
        feedbackVerdict: asStringOrNull(json['feedback_verdict']),
      );

  final String id;
  final String kind;
  final DateTime createdAt;
  final String? modelName;
  final String? modelVersion;
  final String? summary;
  final String? dataClass;
  final String? cropCode;
  final String? feedbackVerdict;
}

class AiHistoryPage {
  const AiHistoryPage({
    required this.items,
    required this.page,
    required this.total,
    required this.totalPages,
    required this.hasNext,
    required this.retentionNote,
  });

  factory AiHistoryPage.fromJson(Map<String, dynamic> json) => AiHistoryPage(
        items: asMapList(json['items']).map(AiHistoryEntry.fromJson).toList(),
        page: asInt(json['page'], fallback: 1),
        total: asInt(json['total']),
        totalPages: asInt(json['total_pages'], fallback: 1),
        hasNext: asBool(json['has_next']),
        retentionNote: asString(json['retention_note']),
      );

  final List<AiHistoryEntry> items;
  final int page;
  final int total;
  final int totalPages;
  final bool hasNext;
  final String retentionNote;
}
