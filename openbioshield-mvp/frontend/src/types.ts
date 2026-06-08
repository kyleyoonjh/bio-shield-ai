export interface SchemaMapping {
  target_column: string;
  group_columns: string[];
}

export interface UploadMetadata {
  filename: string;
  column_count: number;
  row_preview_count: number;
  columns: Array<{
    name: string;
    dtype: string;
    sample_values: string[];
  }>;
}

export interface StatsResult {
  anova: { f_value: number; p_value: number };
  repeatability: { sd: number; cv_percent: number };
  reproducibility: { sd: number; cv_percent: number };
  variance_components: {
    within_group: number;
    between_group: number;
    within_group_percent: number;
    between_group_percent: number;
  };
  grand_mean: number;
  sample_count: number;
  groups: Array<{
    group: string;
    mean: number;
    sd: number;
    n: number;
    cv_percent: number;
  }>;
  target_column: string;
  group_columns: string[];
}

export interface BioAnnotation {
  name: string;
  start: number;
  end: number;
  color: string;
  strand: number;
}

export interface BioContext {
  rdrp_sequence: string;
  annotations: BioAnnotation[];
  primer_structure: {
    sequence: string;
    dot_bracket: string;
    melting_temp_c: number;
    delta_g_kcal: number;
    gc_percent: number;
    length: number;
  };
  assay_info: {
    target_gene: string;
    organism: string;
    assay_type: string;
    standard: string;
  };
}
