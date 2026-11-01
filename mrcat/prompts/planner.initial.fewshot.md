Illustrative IDs and study names are not existing data.
Request: Search xxx_exposure and xxx_outcome in OpenGWAS and run a quick baseline.
{"plan_items":[
{"step_id":"search_xxx_exposure","title":"Search OpenGWAS for exposure xxx_exposure","skill_id":"gwas-search","reuse_from":[]},
{"step_id":"search_xxx_outcome","title":"Search OpenGWAS for outcome xxx_outcome","skill_id":"gwas-search","reuse_from":[]},
{"step_id":"select_studies","title":"Select the requested xxx_exposure and xxx_outcome studies from both searches, preserving fixed IDs and compatible ancestry","skill_id":"gwas-select","reuse_from":[]},
{"step_id":"fit_pair","title":"Run quick primary MR from selected exposure xxx_exposure to selected outcome xxx_outcome","skill_id":"mr-primary-id","reuse_from":[]}
]}

Request: Use the two supplied raw files to run a method unavailable in Skill Options.
{"plan_items":[
{"step_id":"qc_exposure","title":"QC the supplied exposure file with the user-provided metadata","skill_id":"gwas-qc","reuse_from":[]},
{"step_id":"qc_outcome","title":"QC the supplied outcome file with the user-provided metadata","skill_id":"gwas-qc","reuse_from":[]},
{"step_id":"inspect_method_requirements","title":"Investigate the requested method's official input fields, scales, IV selection, LD handling and resources against both QC results; publish the source evidence and whether shared pair preparation is compatible, then hand off to Review before preparation or fitting","skill_id":null,"reuse_from":[]}
]}
This is a staged plan, not a completed analysis. Review accepts the investigation
and requests a plan for preparation and fitting. Do not add this investigation
when a compatible Skill or accepted saved investigation already establishes the route.


Request: Use the supplied gene-expression association file and trait GWAS to test
the gene's expression effect using its documented cis region. The files have
verified allele, build and sample metadata; the analysis needs regional variants
that the formatted GWAS filtering and genome-wide background pipeline would not
preserve. Keep the existing scientific inputs.
{"plan_items":[
{"step_id":"qc_studies","title":"Validate and format the supplied expression and trait associations separately, preserving native effects, tissue/gene identity and the regional variants needed downstream","skill_id":null,"reuse_from":[]},
{"step_id":"prepare_pair","title":"Select justified cis instruments for the documented gene region, harmonize expression and trait effects and assess instrument strength and LD with a compatible reference; retain regional associations for colocalization","skill_id":null,"reuse_from":[]},
{"step_id":"fit_expression_mr","title":"Estimate the expression-to-trait effect with a method appropriate to the observed instrument count and LD structure, preserving effect-scale provenance and reporting insufficiency when necessary","skill_id":null,"reuse_from":[]},
{"step_id":"validate_expression_mr","title":"Perform sensitivity checks applicable to the fitted model and evaluate regional colocalization when the available data support it; report unresolved assumptions and data limitations","skill_id":null,"reuse_from":[]}
]}
These are familiar analysis operations with custom implementations, not omitted
steps or a request to build new skills. Reuse existing skills whenever their
actual contracts fit a different case; molecular data do not imply all-custom
execution. Unsupported validation cannot be claimed as completed.
