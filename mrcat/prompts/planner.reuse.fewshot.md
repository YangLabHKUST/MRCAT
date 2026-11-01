Reuse and recovery item guidance. References below are illustrative; use only actual available sources.
Historical request: Continue with CAUSE using the two uniquely identified QC results in task_xxx.
{"plan_items":[{"step_id":"cause_reused_pair","title":"Reuse task_xxx's exposure and outcome QC studies to run CAUSE in the same direction","skill_id":"mr-cause","reuse_from":["task_xxx/qc_exposure/gwas_qc_result","task_xxx/qc_outcome/gwas_qc_result"]}]}

Current-task recovery: qc_exposure and qc_outcome completed, but pair preparation failed.
{"plan_items":[{"step_id":"prepare_pair","title":"Prepare the requested directed pair using the completed qc_exposure and qc_outcome results","skill_id":"gwas-pair-prepare","reuse_from":[]},{"step_id":"fit_pair","title":"Run BWMR on the prepared pair","skill_id":"mr-bwmr","reuse_from":[]}]}
Preserve completed results even when their steps are omitted from the remaining plan. Never list their output fields as requirements. If no supported continuation exists, Review should finalize with the evidenced boundary rather than request endless inspection.

Upstream recovery: Review invalidated producer_xxx because its output violates the input contract of consumer_xxx. Reopen producer_xxx with the supported correction, then continue the affected consumers. Preserve valid independent branches and the user's scientific constraints. The old publication remains audit evidence and cannot be reused.


Request: Continue a stopped expression-to-trait analysis using the same selected
studies and completed downloads. The unfinished pair-preparation tool requires
genome-wide background estimation that the expression data do not support.
Keep the scientific operations and replace the unsuitable implementation; do not
redownload or create another task. Assuming compatible QC results are already
completed in the active task:
{"plan_items":[
{"step_id":"prepare_pair","title":"Use the completed compatible study outputs to prepare the expression-to-trait pair with the justified gene region, instrument selection, harmonization and LD handling, without unsupported genome-wide background estimation","skill_id":null,"reuse_from":[]},
{"step_id":"fit_expression_mr","title":"Fit expression-to-trait MR using the prepared instruments and an estimator appropriate to their count and LD structure; publish the actual estimate and provenance","skill_id":null,"reuse_from":[]},
{"step_id":"validate_expression_mr","title":"Run validation appropriate to the expression-MR fit, including regional colocalization if supported by the available association data; report unresolved evidence","skill_id":null,"reuse_from":[]}
]}
Only the incompatible implementation is replaced. If QC is not complete or its
filtering discarded required regional evidence, include that missing or invalid
preparation first while preserving valid downloaded files.


Accepted investigation: inspect_method_requirements verified that method_xxx
consumes independent harmonized instruments, with final exposure P <= 5e-8 and
compatible effect scales. Both QC studies support the shared preparation's
EUR LDSC and clumping assumptions. No compatible pair is already prepared.
Review requests replan with accept_item=true; the investigation is completed.
{"plan_items":[
{"step_id":"prepare_pair","title":"Prepare the directed pair from completed qc_exposure and qc_outcome using the verified compatible shared workflow; preserve the initial IV ceiling of 5e-5 and record actual selection and LD settings","skill_id":"gwas-pair-prepare","reuse_from":[]},
{"step_id":"fit_method","title":"Run method_xxx using prepare_pair and the accepted inspect_method_requirements evidence; apply its final IV P-value cutoff of 5e-8 to the initial 5e-5 candidate set exactly once, validate scale and LD compatibility, and publish the fit with effective threshold and SNP count","skill_id":null,"reuse_from":[]}
]}
The numeric settings above are established facts of this example, not defaults
for arbitrary methods. Reuse an existing compatible pair instead of preparing it
again; methods that consume the complete prepared set need no extra filtering.

Accepted investigation: inspect_method_requirements verified that method_yyy
needs correlated candidates and a matching LD matrix. The completed QC outputs
retain the required variants and fields; the historical clumped MRdat does not.
{"plan_items":[
{"step_id":"prepare_method_inputs","title":"Prepare method_yyy inputs from completed qc_exposure and qc_outcome according to the accepted inspect_method_requirements evidence, retaining its required candidates and building compatible LD resources; validate and publish the inputs and provenance","skill_id":null,"reuse_from":[]},
{"step_id":"fit_method","title":"Fit and validate method_yyy using prepare_method_inputs and its established official settings; publish results with selection, scale, resource provenance and interpretation limits","skill_id":null,"reuse_from":[]}
]}
Keep the accepted investigation and QC results. Neither the need for an extra
resource nor its absence alone establishes compatibility with shared preparation.
