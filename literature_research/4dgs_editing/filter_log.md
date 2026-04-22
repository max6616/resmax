# Literature Filtering Log

**Direction**: 4D Gaussian Splatting for dynamic 3D scene editing and manipulation
**Keywords**: 4DGS, 4D Gaussian Splatting, dynamic scene editing, deformable Gaussian, dynamic 3D editing, temporal Gaussian, Gaussian splatting editing, dynamic NeRF editing, 4D scene manipulation, space-time Gaussian
**Total elapsed**: 52778.1s

---

## Stage 1: Dual-path Retrieval

- Keyword search: 60 matches, kept top 50
- Embedding search: 50 candidates (cache size: 49152)
- Stage time: 29.7s

## Stage 2: Dedup & Merge

- Pre-dedup total: 100
- Duplicates removed: 18
- Merged candidates: 82
  - keyword only: 32
  - embedding only: 32
  - both: 18
- Stage time: 0.0s

## Stage 3: Meta Enrichment

- Has abstract: 82/82
- Has PDF link: 49/82
- Missing abstract: 0
- Missing PDF: 33
- Stage time: 0.0s

## Stage 5: Subagent Scoring

- Papers scored: 82
- Stage time: 0.0s

| # | Paper ID | Title (truncated) | Score | Reason |
|---|----------|-------------------|-------|--------|
| 1 | ACMMM_2025::d_gaussi | D²Gaussian: Dynamic Control with Discretized 3D Vi... | S | Text-driven 3DGS editing with dynamic control. |
| 2 | CVPR_2024::4d_gaussi | 4D Gaussian Splatting for Real-Time Dynamic Scene ... | S | Foundational 4D-GS paper introducing core representation com... |
| 3 | CVPR_2025::ctrl_d_co | CTRL-D: Controllable Dynamic 3D Scene Editing with... | S | Directly addresses controllable editing of dynamic 3D scenes... |
| 4 | CVPR_2025::efficient | Efficient Dynamic Scene Editing via 4D Gaussian-ba... | S | Directly addresses efficient editing of 4D dynamic scenes us... |
| 5 | CVPR_2024::instruct_ | Instruct 4D-to-4D: Editing 4D Scenes as Pseudo-3D ... | S | Directly addresses instruction-guided editing of 4D dynamic ... |
| 6 | CVPR_2024::sc_gs_spa | SC-GS: Sparse-Controlled Gaussian Splatting for Ed... | S | Sparse-controlled GS for editable dynamic scenes, directly a... |
| 7 | ECCV_2024::gaussctrl | GaussCtrl: Multi-View Consistent Text-Driven 3D Ga... | S | Multi-view consistent text-driven 3DGS editing. |
| 8 | ECCV_2024::texture_g | Texture-GS: Disentangle the Geometry and Texture f... | S | Geometry-texture disentanglement for 3DGS editing. |
| 9 | ICCV_2025::intergsed | InterGSEdit: Interactive 3D Gaussian Splatting Edi... | S | Title contains editing; core 3DGS editing method. |
| 10 | ICLR_2024::real_time | Real-time Photorealistic Dynamic Scene Representat... | S | 4DGS with 4D Gaussian primitives and anisotropic ellipses ro... |
| 11 | NeurIPS_2024::d_miso | D-MiSo: Editing Dynamic 3D Scenes using Multi-Gaus... | S | Text-driven 3DGS editing with dynamic control, directly addr... |
| 12 | AAAI_2025::efficient | Efficient Gaussian Splatting for Monocular Dynamic... | A | 4D/dynamic GS for monocular dynamic scenes, efficient render... |
| 13 | AAAI_2025::motion_de | Motion Decoupled 3D Gaussian Splatting for Dynamic... | A | Dynamic 3DGS for dynamic object representation, core 4DGS me... |
| 14 | ACMMM_2025::cadgs_mo | CaDGS: Modeling Inter-Gaussian Mutual Information ... | A | 4DGS for dynamic novel view synthesis, relevant methodology. |
| 15 | ACMMM_2025::dynamic_ | Dynamic 2D Gaussians: Geometrically Accurate Radia... | A | 4DGS for dynamic objects with geometry focus, reconstruction... |
| 16 | ACMMM_2025::e_4dgs_h | E-4DGS: High-Fidelity Dynamic Reconstruction from ... | A | 4DGS for dynamic reconstruction with event cameras, not edit... |
| 17 | ACMMM_2025::futuregs | FutureGS: Structured Gaussian Fields for Future-Aw... | A | 4DGS for dynamic scenes with structured fields, focuses on f... |
| 18 | ACMMM_2025::see_thro | See Through the Occlusions: Amodal Gaussian Splatt... | A | Reinterprets time as deformation axis with opacity modulatio... |
| 19 | ACMMM_2025::sparse4d | Sparse4DGS: Flow-Geometry Assisted 4D Gaussian Spl... | A | 4DGS for sparse-view synthesis. Core building block but focu... |
| 20 | CVPR_2024::3d_geomet | 3D Geometry-Aware Deformable Gaussian Splatting fo... | A | Deformable GS for dynamic view synthesis with 3D geometry co... |
| 21 | CVPR_2024::align_you | Align Your Gaussians: Text-to-4D with Dynamic 3D G... | A | Text-to-4D with dynamic 3D Gaussians, core 4DGS generation m... |
| 22 | CVPR_2024::deformabl | Deformable 3D Gaussians for High-Fidelity Monocula... | A | Deformable 3DGS for dynamic reconstruction, core deformation... |
| 23 | CVPR_2025::drivedrea | DriveDreamer4D: World Models Are Effective Data Ma... | A | 4D driving scene representation using GS, but focused on dri... |
| 24 | CVPR_2024::feature_3 | Feature 3DGS: Supercharging 3D Gaussian Splatting ... | A | Feature distillation for 3DGS enabling semantic editing appl... |
| 25 | CVPR_2025::gifstream | GIFStream: 4D Gaussian-based Immersive Video with ... | A | 4DGS for immersive video, relevant 4DGS method but not editi... |
| 26 | CVPR_2025::himor_mon | HiMoR: Monocular Deformable Gaussian Reconstructio... | A | Deformable GS for dynamic reconstruction with hierarchical m... |
| 27 | CVPR_2025::ntr_gauss | NTR-Gaussian: Nighttime Dynamic Thermal Reconstruc... | A | 4DGS for dynamic thermal reconstruction, core 4DGS method. |
| 28 | CVPR_2025::robust_mu | Robust Multi-Object 4D Generation for In-the-wild ... | A | Deformable 4DGS for dynamic scene generation from video, rel... |
| 29 | CVPR_2024::spacetime | Spacetime Gaussian Feature Splatting for Real-Time... | A | Spacetime GS for dynamic view synthesis, core 4DGS method. |
| 30 | CVPR_2025::splatflow | SplatFlow: Self-Supervised Dynamic Gaussian Splatt... | A | Dynamic GS for autonomous driving, reconstruction-focused. |
| 31 | ECCV_2024::a_compact | A Compact Dynamic 3D Gaussian Representation for R... | A | Dynamic GS for few-shot reconstruction, view synthesis focus... |
| 32 | ECCV_2024::dgd_dynam | DGD: Dynamic 3D Gaussians Distillation | A | Dynamic 3D Gaussians with semantic distillation, relevant 4D... |
| 33 | ECCV_2024::per_gauss | Per-Gaussian Embedding-Based Deformation for Defor... | A | Per-Gaussian deformation for deformable 3DGS, core deformati... |
| 34 | ECCV_2024::stag4d_sp | STAG4D: Spatial-Temporal Anchored Generative 4D Ga... | A | 4DGS for dynamic scene generation, relevant 4DGS technique. |
| 35 | ECCV_2024::swings_sl | SWinGS: Sliding Windows for Dynamic 3D Gaussian Sp... | A | Dynamic GS for novel view synthesis, core 4DGS method. |
| 36 | ICCV_2025::4d_gaussi | 4D Gaussian Splatting SLAM | A | 4DGS for SLAM, shares core 4DGS methodology but focuses on l... |
| 37 | ICCV_2025::7dgs_unif | 7DGS: Unified Spatial-Temporal-Angular Gaussian Sp... | A | Extends 4DGS by unifying spatial-temporal-angular dimensions... |
| 38 | ICCV_2025::degauss_d | DeGauss: Dynamic-Static Decomposition with Gaussia... | A | Dynamic-static decomposition with GS, relevant for editing i... |
| 39 | ICCV_2025::emd_expli | EMD: Explicit Motion Modeling for High-Quality Str... | A | 4DGS for dynamic street scenes with explicit motion, reconst... |
| 40 | ICCV_2025::gaussianu | GaussianUpdate: Continual 3D Gaussian Splatting Up... | A | Continual 3DGS update for changing environments. |
| 41 | ICCV_2025::localdygs | LocalDyGS: Multi-view Global Dynamic Scene Modelin... | A | Dynamic GS for multi-view dynamic scene modeling, core 4DGS ... |
| 42 | ICCV_2025::mega_memo | MEGA: Memory-Efficient 4D Gaussian Splatting for D... | A | Memory-efficient 4DGS for dynamic scenes, methodological ove... |
| 43 | ICLR_2025::dynamic_g | Dynamic Gaussians Mesh: Consistent Mesh Reconstruc... | A | Dynamic Gaussians with mesh output, reconstruction not editi... |
| 44 | ICLR_2025::swift4d_a | Swift4D: Adaptive divide-and-conquer Gaussian Spla... | A | 4DGS for compact/efficient dynamic reconstruction. |
| 45 | ICML_2024::superpoin | Superpoint Gaussian Splatting for Real-Time High-F... | A | 4D scene generation with video diffusion, relevant 4D conten... |
| 46 | NeurIPS_2024::4d_gau | 4D Gaussian Splatting in the Wild with Uncertainty... | A | 4DGS with regularization for dynamic scenes. Significant ove... |
| 47 | NeurIPS_2025::4d3r_m | 4D3R: Motion-Aware Neural Reconstruction and Rende... | A | 4DGS for dynamic reconstruction from monocular video. |
| 48 | NeurIPS_2025::4dgt_l | 4DGT: Learning a 4D Gaussian Transformer Using Rea... | A | 4D Gaussian Transformer for dynamic reconstruction, relevant... |
| 49 | NeurIPS_2025::dgs_lr | DGS-LRM: Real-Time Deformable 3D Gaussian Reconstr... | A | Deformable GS reconstruction from monocular video, feed-forw... |
| 50 | NeurIPS_2024::dn_4dg | DN-4DGS: Denoised Deformable Network with Temporal... | A | 4DGS with deformable networks for dynamic rendering, relevan... |
| 51 | NeurIPS_2024::fully_ | Fully Explicit Dynamic Gaussian Splatting | A | Explicit 4DGS with static/dynamic separation. Core represent... |
| 52 | NeurIPS_2025::haif_g | HAIF-GS: Hierarchical and Induced Flow-Guided Gaus... | A | 4DGS with hierarchical attention for dynamic reconstruction. |
| 53 | NeurIPS_2025::holigs | HoliGS: Holistic Gaussian Splatting for Embodied V... | A | Deformable/4D GS for dynamic scenes with hierarchical decomp... |
| 54 | NeurIPS_2024::motion | MotionGS: Exploring Explicit Motion Guidance for D... | A | Deformable 3DGS with explicit motion, reconstruction-focused... |
| 55 | SIGGRAPH_2025::splat | Splat4D: Diffusion-Enhanced 4D Gaussian Splatting ... | A | 4DGS content creation, not editing/manipulation. |
| 56 | SIGGRAPH_Asia_2025:: | Anchored 4D Gaussian Splatting for Dynamic Novel V... | A | 4DGS for dynamic reconstruction from event cameras. |
| 57 | SIGGRAPH_Asia_2025:: | Clustered Error Correction with Grouped 4D Gaussia... | A | 4DGS for dynamic scene reconstruction with error correction,... |
| 58 | SIGGRAPH_Asia_2025:: | Neural Texture Splatting: Expressive 3D Gaussian S... | A | 3DGS extended to 4D/dynamic reconstruction, view synthesis. |
| 59 | SIGGRAPH_Asia_2025:: | TrackerSplat: Exploiting Point Tracking for Fast a... | A | Dynamic 3DGS reconstruction with point tracking. |
| 60 | ACMMM_2025::dgns_def | DGNS: Deformable Gaussian Splatting and Dynamic Ne... | B | Deformable GS for reconstruction, not editing/manipulation. |
| 61 | ACMMM_2025::holotime | HoloTime: Taming Video Diffusion Models for Panora... | B | Panoramic 4D scene generation, not editing. |
| 62 | CVPR_2025::anigs_ani | AniGS: Animatable Gaussian Avatar from a Single Im... | B | Animatable avatar from single image, not scene editing. |
| 63 | CVPR_2025::generativ | Generative Sparse-View Gaussian Splatting | B | Sparse-view 3DGS for novel view synthesis, not 4D or editing... |
| 64 | CVPR_2025::improving | Improving Gaussian Splatting with Localized Points... | B | Improves 3DGS optimization, foundational but not 4D or editi... |
| 65 | CVPR_2025::voxelspla | VoxelSplat: Dynamic Gaussian Splatting as an Effec... | B | Dynamic GS as loss for occupancy/flow prediction, tangential... |
| 66 | ICCV_2025::coda_4dgs | CoDa-4DGS: Dynamic Gaussian Splatting with Context... | B | 4DGS for autonomous driving rendering, not editing/manipulat... |
| 67 | ICCV_2025::gsv3d_gau | GSV3D: Gaussian Splatting-based Geometric Distilla... | B | 3DGS for single-image 3D generation, not dynamic/4D editing. |
| 68 | ICCV_2025::generativ | Generative Gaussian Splatting: Generating 3D Scene... | B | GS with generative priors for static scene synthesis. |
| 69 | ICCV_2025::interacta | InteractAvatar: Modeling Hand-Face Interaction in ... | B | Deformable Gaussians for avatar modeling, avatar-specific no... |
| 70 | ICCV_2025::robustspl | RobustSplat: Decoupling Densification and Dynamics... | B | Robustness of 3DGS in dynamic scenes, transient removal. |
| 71 | NeurIPS_2025::1000_f | 1000+ FPS 4D Gaussian Splatting for Dynamic Scene ... | B | Focuses on rendering speed optimization for 4DGS, not editin... |
| 72 | NeurIPS_2024::neurog | NeuroGauss4D-PCI: 4D Neural Fields and Gaussian De... | B | 4D neural fields for point cloud interpolation, not GS editi... |
| 73 | NeurIPS_2025::spike4 | Spike4DGS: Towards High-Speed Dynamic Scene Render... | B | 4DGS with spike cameras, specialized sensor input not editin... |
| 74 | NeurIPS_2025::tempor | Temporal Smoothness-Aware Rate-Distortion Optimize... | B | 4DGS compression/storage efficiency, not editing. |
| 75 | SIGGRAPH_Asia_2025:: | Virtually Being: Customizing Camera-Controllable V... | B | 4DGS as data source for video diffusion, not editing. |
| 76 | CVPR_2025::go_with_t | Go-with-the-Flow: Motion-Controllable Video Diffus... | C | Motion-controllable video diffusion, no GS or 3D/4D scene ed... |
| 77 | ECCV_2024::watching_ | Watching it in Dark: A Target-aware Representation... | C | Low-light vision, no connection to GS or 3D/4D editing. |
| 78 | ICCV_2025::mixture_o | Mixture of Experts Guided by Gaussian Splatters Ma... | C | GS for video anomaly detection, unrelated to scene editing. |
| 79 | ICLR_2025::an_explor | An Exploration with Entropy Constrained 3D Gaussia... | C | 3DGS for video compression, peripheral application. |
| 80 | ICLR_2024::bidirecti | Bidirectional Temporal Diffusion Model for Tempora... | C | Human animation via diffusion, no GS or 3D/4D editing. |
| 81 | ICML_2025::optimal_s | Optimal Sensor Scheduling and Selection for Contin... | C | Sensor scheduling for Kalman filtering, unrelated to GS. |
| 82 | ICML_2025::robust_an | Robust and Conjugate Spatio-Temporal Gaussian Proc... | C | Gaussian process regression, unrelated to Gaussian Splatting... |

## Stage 7: Final Distribution

- S: 11
- A: 48
- B: 16
- C: 7
- Total: 82

## Timing Summary

| Stage | Time (s) |
|-------|----------|
| merge | 0.0 |
| meta_enrich | 0.0 |
| retrieval | 29.7 |
| **total** | **52778.1** |

## Stage 5.5: Openness Deep Check (S papers only)

- Total S papers: 11
- Source cached (arxiv TeX): 5
- Source cached (mineru MD): 5
- No source (no arxiv_id and no PDF URL): 1
- Repo reviews dispatched: 8
- code_quality=full: 7
- code_quality=project_page_only: 1 (CTRL-D)
- code_quality=unknown (could not reach repo): 3

Details in `deepcheck_results.md` and `deepcheck_reviews.json`.
