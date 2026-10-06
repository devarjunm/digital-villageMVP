import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../app.dart';
import '../../core/api_exception.dart';
import '../../models/community.dart';
import '../../models/farm.dart';
import '../../widgets/common.dart';

/// Creates a post (`POST /community/posts`, photo via `POST /media/upload`).
///
/// The category list comes from `/community/meta` and the crop list from
/// `/crops/catalog`, so the vocabulary matches what the ranking and the
/// moderation queue operate on. Source links are optional but encouraged, since
/// a claim with a source can be checked by a moderator or an expert.
class CreatePostScreen extends StatefulWidget {
  const CreatePostScreen({super.key});

  @override
  State<CreatePostScreen> createState() => _CreatePostScreenState();
}

class _CreatePostScreenState extends State<CreatePostScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  final _sources = TextEditingController();
  final _picker = ImagePicker();

  CommunityMeta? _meta;
  List<CropCatalogEntry> _catalog = const [];
  List<Farm> _farms = const [];

  String? _category;
  String? _cropCode;
  String _language = 'en';
  String? _state;
  String? _district;
  String? _farmId;
  Uint8List? _photo;
  String? _photoName;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _language = context.session.languageCode;
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrap());
  }

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    _sources.dispose();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    final repos = context.repos;
    final signedIn = context.session.isSignedIn;
    try {
      final meta = await repos.community.meta();
      final catalog = await repos.crops.catalog();
      List<Farm> farms = const [];
      if (signedIn) {
        farms = await repos.farms.list();
      }
      if (!mounted) return;
      setState(() {
        _meta = meta;
        _catalog = catalog;
        _farms = farms;
        _category =
            meta.categories.isNotEmpty ? meta.categories.first.value : null;
        _state = context.session.profile?.state;
        _district = context.session.profile?.district;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    }
  }

  Future<void> _pickPhoto() async {
    final picked = await _picker.pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600,
      maxHeight: 1600,
      imageQuality: 85,
    );
    if (picked == null) return;
    final bytes = await picked.readAsBytes();
    if (!mounted) return;
    setState(() {
      _photo = bytes;
      _photoName = picked.name.isEmpty ? 'post.jpg' : picked.name;
    });
  }

  Future<void> _publish() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final repos = context.repos;
    try {
      final mediaIds = <String>[];
      if (_photo != null) {
        final asset = await repos.ai.uploadImage(
          bytes: _photo!,
          filename: _photoName ?? 'post.jpg',
          purpose: 'post_image',
        );
        mediaIds.add(asset.id);
      }
      final urls = _sources.text
          .split('\n')
          .map((line) => line.trim())
          .where((line) => line.startsWith('http'))
          .toList();

      final post = await repos.community.createPost({
        'title': _title.text.trim(),
        'body': _body.text.trim(),
        'category': _category,
        'language': _language,
        if (_cropCode != null) 'crop_code': _cropCode,
        if (_state != null && _state!.isNotEmpty) 'state': _state,
        if (_district != null && _district!.isNotEmpty) 'district': _district,
        'media_ids': mediaIds,
        'source_urls': urls,
        if (_farmId != null) 'farm_id': _farmId,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(context.t('post_published'))),
      );
      Navigator.of(context).pop(post.id);
    } on ApiException catch (error) {
      setState(() {
        _busy = false;
        _error = error.userFieldsOrMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final languageCode = context.session.languageCode;
    final meta = _meta;
    return Scaffold(
      appBar: AppBar(title: Text(context.t('create_post'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
        children: [
          Notice(
            kind: NoticeKind.info,
            title: context.t('trust_label'),
            message:
                'The platform labels every post with how its information should be read. '
                'Adding a source link lets others verify it.',
          ),
          const SizedBox(height: 14),
          if (_error != null) ...[
            Notice(
                kind: NoticeKind.danger,
                title: context.t('error_title'),
                message: _error!),
            const SizedBox(height: 14),
          ],
          SectionCard(
            title: context.t('create_post'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FormTextField(
                  label: context.t('post_title'),
                  controller: _title,
                  required: true,
                  maxLines: 2,
                ),
                FormTextField(
                  label: context.t('post_body'),
                  controller: _body,
                  required: true,
                  maxLines: 8,
                  helper:
                      'Describe what you observed: crop, stage, when it started, what you tried.',
                ),
                if (meta != null)
                  DropdownField<String>(
                    label: context.t('category'),
                    value: _category,
                    items:
                        meta.categories.map((option) => option.value).toList(),
                    allowNull: false,
                    labelBuilder: (value) => meta.categories
                        .firstWhere(
                          (option) => option.value == value,
                          orElse: () => MetaOption(value: value, label: value),
                        )
                        .label,
                    onChanged: (value) => setState(() => _category = value),
                  ),
                DropdownField<String>(
                  label: context.t('crop'),
                  value: _cropCode,
                  items: _catalog.map((entry) => entry.code).toList(),
                  labelBuilder: (code) => _catalog
                      .firstWhere(
                        (entry) => entry.code == code,
                        orElse: () => CropCatalogEntry(
                          code: code,
                          nameEn: code,
                          category: '',
                          season: '',
                          defaultAreaUnit: 'acre',
                        ),
                      )
                      .localizedName(languageCode),
                  onChanged: (value) => setState(() => _cropCode = value),
                ),
                DropdownField<String>(
                  label: context.t('language'),
                  value: _language,
                  items: const ['en', 'mr', 'hi'],
                  allowNull: false,
                  labelBuilder: (value) => switch (value) {
                    'mr' => 'मराठी',
                    'hi' => 'हिंदी',
                    _ => 'English',
                  },
                  onChanged: (value) =>
                      setState(() => _language = value ?? 'en'),
                ),
                Row(
                  children: [
                    Expanded(
                      child: FormTextField(
                        label: context.t('district'),
                        controller:
                            TextEditingController(text: _district ?? ''),
                        onChanged: (value) => _district = value,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FormTextField(
                        label: context.t('state'),
                        controller: TextEditingController(text: _state ?? ''),
                        onChanged: (value) => _state = value,
                      ),
                    ),
                  ],
                ),
                if (_farms.isNotEmpty)
                  DropdownField<String>(
                    label: context.t('nav_farm'),
                    value: _farmId,
                    items: _farms.map((farm) => farm.id).toList(),
                    labelBuilder: (id) =>
                        _farms.firstWhere((farm) => farm.id == id).name,
                    onChanged: (value) => setState(() => _farmId = value),
                  ),
                FormTextField(
                  label: context.t('source_links'),
                  controller: _sources,
                  maxLines: 3,
                  helper: context.t('source_links_hint'),
                ),
                if (_photo != null) ...[
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child:
                        Image.memory(_photo!, height: 160, fit: BoxFit.cover),
                  ),
                  const SizedBox(height: 8),
                  TextButton.icon(
                    onPressed: () => setState(() {
                      _photo = null;
                      _photoName = null;
                    }),
                    icon: const Icon(Icons.close, size: 16),
                    label: Text(context.t('cancel')),
                  ),
                ] else
                  OutlinedButton.icon(
                    onPressed: _pickPhoto,
                    icon: const Icon(Icons.photo_library_outlined, size: 18),
                    label: Text(context.t('attach_photo')),
                  ),
                const SizedBox(height: 16),
                BusyButton(
                  label: context.t('publish'),
                  busy: _busy,
                  icon: Icons.send,
                  onPressed:
                      _title.text.trim().isEmpty || _body.text.trim().isEmpty
                          ? null
                          : _publish,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
