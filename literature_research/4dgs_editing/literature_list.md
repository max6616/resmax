# Literature List: 4D Gaussian Splatting for dynamic 3D scene editing and manipulation

**Total**: 82

**Distribution**: S=11, A=48, B=16, C=7

---

## Grade S

### 1. [S] 4D Gaussian Splatting for Real-Time Dynamic Scene Rendering
**CVPR 2024 | Guanjun Wu; Taoran Yi; Jiemin Fang; Lingxi Xie; Xiaopeng Zhang; Wei Wei; Weny...**
[PDF](https://arxiv.org/pdf/2310.08528.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Wu_4D_Gaussian_Splatting_for_Real-Time_Dynamic_Scene_Rendering_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2310.08528)
Source: both
**AI Assessment**: Foundational 4D-GS paper introducing core representation combining 3D Gaussians with 4D neural voxels for dynamic scene rendering. Primary baseline for any 4DGS editing work.
> Representing and rendering dynamic scenes has been an important but challenging task. Especially, to accurately model complex motions, high efficiency is usually hard to guarantee. To achieve real-time dynamic scene rendering while also enjoying high training and storage efficiency, we propose 4D Ga...

### 2. [S] Real-time Photorealistic Dynamic Scene Representation and Rendering with 4D Gaussian Splatting
**ICLR 2024 | Zeyu Yang; Hongye Yang; Zijie Pan; Li Zhang**
[Paper](https://iclr.cc/virtual/2024/poster/18466)
Source: both
**AI Assessment**: 4DGS with 4D Gaussian primitives and anisotropic ellipses rotating in space-time. Essential baseline and foundational work.
> Reconstructing dynamic 3D scenes from 2D images and generating diverse views over time is challenging due to scene complexity and temporal dynamics. Despite advancements in neural implicit models, limitations persist: (i) Inadequate Scene Structure: Existing methods struggle to reveal the spatial an...

### 3. [S] Efficient Dynamic Scene Editing via 4D Gaussian-based Static-Dynamic Separation
**CVPR 2025 | Joohyun Kwon; Hanbyel Cho; Junmo Kim**
[PDF](https://arxiv.org/pdf/2502.02091.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Kwon_Efficient_Dynamic_Scene_Editing_via_4D_Gaussian-based_Static-Dynamic_Separation_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2502.02091)
Source: both
**AI Assessment**: Directly addresses efficient editing of 4D dynamic scenes using 4DGS with static-dynamic separation.
> Recent 4D dynamic scene editing methods require editing thousands of 2D images used for dynamic scene synthesis and updating the entire scene with additional training loops, resulting in several hours of processing to edit a single dynamic scene. Therefore, these methods are not scalable with respec...

### 4. [S] InterGSEdit: Interactive 3D Gaussian Splatting Editing with 3D Geometry-Consistent Attention Prior
**ICCV 2025 | Minghao Wen; Shengjie Wu; Kangkan Wang; Dong Liang**
[PDF](https://arxiv.org/pdf/2507.04961.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Wen_InterGSEdit_Interactive_3D_Gaussian_Splatting_Editing_with_3D_Geometry-Consistent_Attention_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2507.04961)
Source: both
**AI Assessment**: Title contains editing; core 3DGS editing method.
> 3D Gaussian Splatting based 3D editing has demonstrated impressive performance in recent years. However, the multi-view editing often exhibits significant local inconsistency, especially in areas of non-rigid deformation, which lead to local artifacts, texture blurring, or semantic variations in edi...

### 5. [S] D-MiSo: Editing Dynamic 3D Scenes using Multi-Gaussians Soup
**NeurIPS 2024 | Joanna Waczynska; Piotr Borycki; Joanna Kaleta; Slawomir Tadeja; Przemysław S...**
[Paper](https://neurips.cc/virtual/2024/poster/96714)
Source: embedding
**AI Assessment**: Text-driven 3DGS editing with dynamic control, directly addresses GS editing.
> Over the past years, we have observed an abundance of approaches for modeling dynamic 3D scenes using Gaussian Splatting (GS). These solutions use GS to represent the scene's structure and the neural network to model dynamics. Such approaches allow fast rendering and extracting each element of such ...

### 6. [S] SC-GS: Sparse-Controlled Gaussian Splatting for Editable Dynamic Scenes
**CVPR 2024 | Yi-Hua Huang; Yang-Tian Sun; Ziyi Yang; Xiaoyang Lyu; Yan-Pei Cao; Xiaojuan Qi**
[PDF](https://openaccess.thecvf.com/content/CVPR2024/papers/Huang_SC-GS_Sparse-Controlled_Gaussian_Splatting_for_Editable_Dynamic_Scenes_CVPR_2024_paper.pdf)
Source: embedding
**AI Assessment**: Sparse-controlled GS for editable dynamic scenes, directly addresses dynamic GS editing.
> Novel view synthesis for dynamic scenes is still a challenging problem in computer vision and graphics. Recently Gaussian splatting has emerged as a robust technique to represent static scenes and enable high-quality and real-time novel view synthesis. Building upon this technique we propose a new r...

### 7. [S] D²Gaussian: Dynamic Control with Discretized 3D View Modeling for Text-Driven 3D Gaussian Splatting Editing
**ACMMM 2025 | Yefei Sheng; Jie Wang; Ming Tao; Bingkun BAO**
Source: keyword
**AI Assessment**: Text-driven 3DGS editing with dynamic control.
> Current advances in text-driven 3D scene editing tasks typically render the 3D representations into multi-view images and modify the images with the text instructions. Context consistency across multiple views and cross-modal consistency in the single-view are the keys to effective 3D editing. Accor...

### 8. [S] CTRL-D: Controllable Dynamic 3D Scene Editing with Personalized 2D Diffusion
**CVPR 2025 | Kai He; Chin-Hsuan Wu; Igor Gilitschenski**
[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/He_CTRL-D_Controllable_Dynamic_3D_Scene_Editing_with_Personalized_2D_Diffusion_CVPR_2025_paper.pdf)
Source: keyword
**AI Assessment**: Directly addresses controllable editing of dynamic 3D scenes.
> Achieving controllable and consistent editing in dynamic 3D scenes remains a significant challenge. Previous work is largely constrained by its editing backbones, resulting in inconsistent edits and limited controllability. We propose to address this challenge using personalized diffusion models. In...

### 9. [S] Instruct 4D-to-4D: Editing 4D Scenes as Pseudo-3D Scenes Using 2D Diffusion
**CVPR 2024 | Linzhan Mou; Jun-Kun Chen; Yu-Xiong Wang**
[PDF](https://openaccess.thecvf.com/content/CVPR2024/papers/Mou_Instruct_4D-to-4D_Editing_4D_Scenes_as_Pseudo-3D_Scenes_Using_2D_CVPR_2024_paper.pdf)
Source: keyword
**AI Assessment**: Directly addresses instruction-guided editing of 4D dynamic scenes.
> This paper proposes Instruct 4D-to-4D that achieves 4D awareness and spatial-temporal consistency for 2D diffusion models to generate high-quality instruction-guided dynamic scene editing results. Traditional applications of 2D diffusion models in dynamic scene editing often result in inconsistency ...

### 10. [S] GaussCtrl: Multi-View Consistent Text-Driven 3D Gaussian Splatting Editing
**ECCV 2024 | Jing Wu; Jiawang Bian; Xinghui Li; Guangrun Wang; Ian Reid; Philip Torr; Vict...**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/02153.pdf)
Source: keyword
**AI Assessment**: Multi-view consistent text-driven 3DGS editing.
> We propose GaussCtrl, a text-driven method to edit a 3D scene reconstructed by the 3D Gaussian Splatting (3DGS). Our method first renders a collection of images by using the 3DGS and edits them by using a pre-trained 2D diffusion model (ControlNet) based on the input prompt, which is then used to op...

### 11. [S] Texture-GS: Disentangle the Geometry and Texture for 3D Gaussian Splatting Editing
**ECCV 2024 | Tian-Xing Xu; WENBO HU; Yu-Kun Lai; Ying Shan; Song-Hai Zhang**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/03567.pdf)
Source: keyword
**AI Assessment**: Geometry-texture disentanglement for 3DGS editing.
> 3D Gaussian splatting, emerging as a groundbreaking approach, has drawn increasing attention for its capabilities of high-fidelity reconstruction and real-time rendering. However, it couples the appearance and geometry of the scene within the Gaussian attributes, which hinders the flexibility of edi...

## Grade A

### 12. [A] Splat4D: Diffusion-Enhanced 4D Gaussian Splatting for Temporally and Spatially Consistent Content Creation
**SIGGRAPH 2025 | Minghao Yin Yukang Cao Songyou Peng Kai Han**
[PDF](https://arxiv.org/pdf/2508.07557.pdf) | [arXiv](https://arxiv.org/abs/2508.07557)
Source: embedding
**AI Assessment**: 4DGS content creation, not editing/manipulation.
> Generating high-quality 4D content from monocular videos for applications such as digital humans and AR/VR poses challenges in ensuring temporal and spatial consistency, preserving intricate details, and incorporating user guidance effectively. To overcome these challenges, we introduce Splat4D, a n...

### 13. [A] Align Your Gaussians: Text-to-4D with Dynamic 3D Gaussians and Composed Diffusion Models
**CVPR 2024 | Huan Ling; Seung Wook Kim; Antonio Torralba; Sanja Fidler; Karsten Kreis**
[PDF](https://arxiv.org/pdf/2312.13763.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Ling_Align_Your_Gaussians_Text-to-4D_with_Dynamic_3D_Gaussians_and_Composed_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2312.13763)
Source: embedding
**AI Assessment**: Text-to-4D with dynamic 3D Gaussians, core 4DGS generation method.
> Text-guided diffusion models have revolutionized image and video generation and have also been successfully used for optimization-based 3D object synthesis. Here, we in-stead focus on the underexplored text-to-4D setting and syn-thesize dynamic, animated 3D objects using score distillation methods w...

### 14. [A] Dynamic 2D Gaussians: Geometrically Accurate Radiance Fields for Dynamic Objects
**ACMMM 2025 | Shuai Zhang; Guanjun Wu; Zhoufeng Xie; Xinggang Wang; Bin Feng; Wenyu Liu**
Source: embedding
**AI Assessment**: 4DGS for dynamic objects with geometry focus, reconstruction not editing.
> Reconstructing objects and extracting high-quality surfaces play a vital role in the real world. Current 4D representations show the ability to render high-quality novel views for dynamic objects, but cannot reconstruct high-quality meshes due to their implicit or geometrically inaccurate representa...

### 15. [A] MotionGS: Exploring Explicit Motion Guidance for Deformable 3D Gaussian Splatting
**NeurIPS 2024 | Ruijie Zhu; Yanzhe Liang; Hanzhi Chang; Jiacheng Deng; Jiahao Lu; Wenfei Yang...**
[Paper](https://neurips.cc/virtual/2024/poster/96538)
Source: embedding
**AI Assessment**: Deformable 3DGS with explicit motion, reconstruction-focused.
> Dynamic scene reconstruction is a long-term challenge in the field of 3D vision. Recently, the emergence of 3D Gaussian Splatting has provided new insights into this problem. Although subsequent efforts rapidly extend static 3D Gaussian to dynamic scenes, they often lack explicit constraints on obje...

### 16. [A] Efficient Gaussian Splatting for Monocular Dynamic Scene Rendering via Sparse Time-Variant Attribute Modeling
**AAAI 2025 | Hanyang Kong; Xingyi Yang; Xinchao Wang**
[PDF](https://ojs.aaai.org/index.php/AAAI/article/view/32460/34615)
Source: both
**AI Assessment**: 4D/dynamic GS for monocular dynamic scenes, efficient rendering rather than editing.
> Rendering dynamic scenes from monocular videos is a crucial yet challenging task. The recent deformable Gaussian Splatting has emerged as a robust solution to represent real-world dynamic scenes. However, it often leads to heavily redundant Gaussians, attempting to fit every training view at various...

### 17. [A] HAIF-GS: Hierarchical and Induced Flow-Guided Gaussian Splatting for Dynamic Scene
**NeurIPS 2025 | Jianing Chen; Zehao Li; Yujun Cai; Hao Jiang; Chengxuan Qian; Juyuan Kang; Sh...**
[Paper](https://neurips.cc/virtual/2025/poster/115007)
Source: embedding
**AI Assessment**: 4DGS with hierarchical attention for dynamic reconstruction.
> Reconstructing dynamic 3D scenes from monocular videos remains a fundamental challenge in 3D vision. While 3D Gaussian Splatting (3DGS) achieves real-time rendering in static settings, extending it to dynamic scenes is challenging due to the difficulty of learning structured and temporally consisten...

### 18. [A] Anchored 4D Gaussian Splatting for Dynamic Novel View Synthesis
**SIGGRAPH_Asia 2025 | Yilong Li; Bo Pang; Yisong Chen; Guoping Wang**
[Paper](https://doi.org/10.1145/3757377.3763898)
Source: embedding
**AI Assessment**: 4DGS for dynamic reconstruction from event cameras.
> Novel view synthesis for dynamic scenes presents a significant challenge in computer graphics. While recent 3D Gaussian splatting methods have achieved state-of-the-art quality and speed for static scenes, their direct extension to 4D dynamic scenes remains non-trivial. Existing approaches for dynam...

### 19. [A] Fully Explicit Dynamic Gaussian Splatting
**NeurIPS 2024 | Junoh Lee; Changyeon Won; Hyunjun Jung; Inhwan Bae; Hae-Gon Jeon**
[Paper](https://neurips.cc/virtual/2024/poster/94164)
Source: both
**AI Assessment**: Explicit 4DGS with static/dynamic separation. Core representation building block for editing.
> 3D Gaussian Splatting has shown fast and high-quality rendering results in static scenes by leveraging dense 3D prior and explicit representations. Unfortunately, the benefits of the prior and representation do not involve novel view synthesis for dynamic motions. Ironically, this is because the mai...

### 20. [A] Sparse4DGS: Flow-Geometry Assisted 4D Gaussian Splatting for Dynamic Sparse View Synthesis
**ACMMM 2025 | Dongdong Hu; Yang Zhou; Xiaofeng Huang; Haibing Yin; Zhu Li**
Source: both
**AI Assessment**: 4DGS for sparse-view synthesis. Core building block but focuses on synthesis not editing.
> Previous dynamic view synthesis works often struggle with limited available views, resulting in noticeable artifacts and blurriness in the outputs. In this paper, we present Sparse4DGS, a novel 4D Gaussian splatting framework that enables high-fidelity view synthesis from sparse inputs through three...

### 21. [A] DN-4DGS: Denoised Deformable Network with Temporal-Spatial Aggregation for Dynamic Scene Rendering
**NeurIPS 2024 | Jiahao Lu; Jiacheng Deng; Ruijie Zhu; Yanzhe Liang; Wenfei Yang; Xu Zhou; Tia...**
[Paper](https://neurips.cc/virtual/2024/poster/95236)
Source: both
**AI Assessment**: 4DGS with deformable networks for dynamic rendering, relevant technique but not editing.
> Dynamic scenes rendering is an intriguing yet challenging problem. Although current methods based on NeRF have achieved satisfactory performance, they still can not reach real-time levels. Recently, 3D Gaussian Splatting (3DGS) has garnered researchers' attention due to their outstanding rendering q...

### 22. [A] Superpoint Gaussian Splatting for Real-Time High-Fidelity Dynamic Scene Reconstruction
**ICML 2024 | Diwen Wan; Ruijie Lu; Gang Zeng**
[Paper](https://proceedings.mlr.press/v235/wan24f.html)
Source: embedding
**AI Assessment**: 4D scene generation with video diffusion, relevant 4D content creation.
> Rendering novel view images in dynamic scenes is a crucial yet challenging task. Current methods mainly utilize NeRF-based methods to represent the static scene and an additional time-variant MLP to model scene deformations, resulting in relatively low rendering quality as well as slow inference spe...

### 23. [A] 3D Geometry-Aware Deformable Gaussian Splatting for Dynamic View Synthesis
**CVPR 2024 | Zhicheng Lu; Xiang Guo; Le Hui; Tianrui Chen; Min Yang; Xiao Tang; Feng Zhu; ...**
[PDF](https://arxiv.org/pdf/2404.06270.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Lu_3D_Geometry-Aware_Deformable_Gaussian_Splatting_for_Dynamic_View_Synthesis_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2404.06270)
Source: both
**AI Assessment**: Deformable GS for dynamic view synthesis with 3D geometry constraints, core 4DGS technique.
> In this paper, we propose a 3D geometry-aware deformable Gaussian Splatting method for dynamic view synthesis. Existing neural radiance fields (NeRF) based solutions learn the deformation in an implicit manner, which cannot incorporate 3D scene geometry. Therefore, the learned deformation is not nec...

### 24. [A] A Compact Dynamic 3D Gaussian Representation for Real-Time Dynamic View Synthesis
**ECCV 2024 | Kai Katsumata; Duc Minh Vo; Hideki Nakayama**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11720.pdf)
Source: embedding
**AI Assessment**: Dynamic GS for few-shot reconstruction, view synthesis focused.
> 3D Gaussian Splatting (3DGS) has shown remarkable success in synthesizing novel views given multiple views of a static scene. Yet, 3DGS faces challenges when applied to dynamic scenes because 3D Gaussian parameters need to be updated per timestep, requiring a large amount of memory and at least a do...

### 25. [A] Feature 3DGS: Supercharging 3D Gaussian Splatting to Enable Distilled Feature Fields
**CVPR 2024 | Shijie Zhou; Haoran Chang; Sicheng Jiang; Zhiwen Fan; Zehao Zhu; Dejia Xu; Pr...**
[PDF](https://arxiv.org/pdf/2312.03203.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Zhou_Feature_3DGS_Supercharging_3D_Gaussian_Splatting_to_Enable_Distilled_Feature_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2312.03203)
Source: embedding
**AI Assessment**: Feature distillation for 3DGS enabling semantic editing applications.
> 3D scene representations have gained immense popularity in recent years. Methods that use Neural Radiance fields are versatile for traditional tasks such as novel view synthesis. In recent times, some work has emerged that aims to extend the functionality of NeRF beyond view synthesis, for semantica...

### 26. [A] Motion Decoupled 3D Gaussian Splatting for Dynamic Object Representation
**AAAI 2025 | Xiao Hu; Libo Long; Jochen Lang**
[PDF](https://ojs.aaai.org/index.php/AAAI/article/view/32373/34528)
Source: embedding
**AI Assessment**: Dynamic 3DGS for dynamic object representation, core 4DGS method.
> Dynamic object modeling is a critical challenge in 3D scene reconstruction. Previous methods typically maintain a canonical space to represent the object model, and a deformation field to express the object motion. However, this approach fails when the object undergoes large motions. The position va...

### 27. [A] 4DGT: Learning a 4D Gaussian Transformer Using Real-World Monocular Videos
**NeurIPS 2025 | Zhen Xu; Zhengqin Li; Zhao Dong; Xiaowei Zhou; Richard Newcombe; Zhaoyang Lv**
[Paper](https://neurips.cc/virtual/2025/poster/115879)
Source: embedding
**AI Assessment**: 4D Gaussian Transformer for dynamic reconstruction, relevant 4DGS technique.
> We propose 4DGT, a 4D Gaussian-based Transformer model for dynamic scene reconstruction, trained entirely on real-world monocular posed videos. Using 4D Gaussian as an inductive bias, 4DGT unifies static and dynamic components, enabling the modeling of complex, time-varying environments with varying...

### 28. [A] DGD: Dynamic 3D Gaussians Distillation
**ECCV 2024 | Isaac Labe; Noam Issachar; Itai Lang; Sagie Benaim**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/08614.pdf)
Source: embedding
**AI Assessment**: Dynamic 3D Gaussians with semantic distillation, relevant 4DGS approach.
> We tackle the task of learning dynamic 3D semantic radiance fields given a single monocular video as input. Our learned semantic radiance field captures per-point semantics as well as color and geometric properties for a dynamic 3D scene, enabling the generation of novel views and their correspondin...

### 29. [A] Spacetime Gaussian Feature Splatting for Real-Time Dynamic View Synthesis
**CVPR 2024 | Zhan Li; Zhang Chen; Zhong Li; Yi Xu**
[PDF](https://arxiv.org/pdf/2312.16812.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Li_Spacetime_Gaussian_Feature_Splatting_for_Real-Time_Dynamic_View_Synthesis_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2312.16812)
Source: both
**AI Assessment**: Spacetime GS for dynamic view synthesis, core 4DGS method.
> Novel view synthesis of dynamic scenes has been an intriguing yet challenging problem. Despite recent advancements, simultaneously achieving high-resolution photorealistic results, real-time rendering, and compact storage remains a formidable task. To address these challenges, we propose Spacetime G...

### 30. [A] SWinGS: Sliding Windows for Dynamic 3D Gaussian Splatting
**ECCV 2024 | Richard Shaw; Michal Nazarczuk; Song Jifei; Arthur Moreau; Sibi Catley-Chanda...**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/07170.pdf)
Source: embedding
**AI Assessment**: Dynamic GS for novel view synthesis, core 4DGS method.
> Novel view synthesis has shown rapid progress recently, with methods capable of producing increasingly photorealistic results. 3D Gaussian Splatting has emerged as a promising method, producing high-quality renderings of scenes and enabling interactive viewing at real-time frame rates. However, it i...

### 31. [A] Deformable 3D Gaussians for High-Fidelity Monocular Dynamic Scene Reconstruction
**CVPR 2024 | Ziyi Yang; Xinyu Gao; Wen Zhou; Shaohui Jiao; Yuqing Zhang; Xiaogang Jin**
[PDF](https://arxiv.org/pdf/2309.13101.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2024/papers/Yang_Deformable_3D_Gaussians_for_High-Fidelity_Monocular_Dynamic_Scene_Reconstruction_CVPR_2024_paper.pdf) | [arXiv](https://arxiv.org/abs/2309.13101)
Source: embedding
**AI Assessment**: Deformable 3DGS for dynamic reconstruction, core deformation method.
> Implicit neural representation has paved the way for new approaches to dynamic scene reconstruction. Nonetheless, cutting-edge dynamic neural rendering methods rely heavily on these implicit representations, which frequently struggle to capture the intricate details of objects in the scene. Furtherm...

### 32. [A] DeGauss: Dynamic-Static Decomposition with Gaussian Splatting for Distractor-free 3D Reconstruction
**ICCV 2025 | Rui Wang; Quentin Lohmeyer; Mirko Meboldt; Siyu Tang**
[PDF](https://arxiv.org/pdf/2503.13176.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Wang_DeGauss_Dynamic-Static_Decomposition_with_Gaussian_Splatting_for_Distractor-free_3D_Reconstruction_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2503.13176)
Source: embedding
**AI Assessment**: Dynamic-static decomposition with GS, relevant for editing infrastructure.
> Reconstructing clean, distractor-free 3D scenes from real-world captures remains a significant challenge, particularly in highly dynamic and cluttered settings such as egocentric videos. To tackle this problem, we introduce DeGauss, a simple and robust self-supervised framework for dynamic scene rec...

### 33. [A] 4D3R: Motion-Aware Neural Reconstruction and Rendering of Dynamic Scenes from Monocular Videos
**NeurIPS 2025 | Mengqi Guo; Bo Xu; Yanyan Li; Gim Hee Lee**
[Paper](https://neurips.cc/virtual/2025/poster/119055)
Source: embedding
**AI Assessment**: 4DGS for dynamic reconstruction from monocular video.
> Novel view synthesis from monocular videos of dynamic scenes with unknown camera poses remains a fundamental challenge in computer vision and graphics. While recent advances in 3D representations such as Neural Radiance Fields (NeRF) and 3D Gaussian Splatting (3DGS) have shown promising results for ...

### 34. [A] 4D Gaussian Splatting in the Wild with Uncertainty-Aware Regularization
**NeurIPS 2024 | Mijeong Kim; Jongwoo Lim; Bohyung Han**
[Paper](https://neurips.cc/virtual/2024/poster/96899)
Source: both
**AI Assessment**: 4DGS with regularization for dynamic scenes. Significant overlap though focuses on novel view synthesis.
> Novel view synthesis of dynamic scenes is becoming important in various applications, including augmented and virtual reality.We propose a novel 4D Gaussian Splatting (4DGS) algorithm for dynamic scenes from casually recorded monocular videos. To overcome the overfitting problem of existing work for...

### 35. [A] FutureGS: Structured Gaussian Fields for Future-Aware Dynamic Scene Modeling
**ACMMM 2025 | Mingyang Ding; Zhan Wang; Jiachen Wang; Tingting Han; Xinyuan Hu; Jiajun Ding...**
Source: both
**AI Assessment**: 4DGS for dynamic scenes with structured fields, focuses on future prediction not editing.
> Recent advances in 4D Gaussian Splatting have boosted dynamic scene reconstruction and real-time rendering. However, current methods remain retrospective, lacking the ability to forecast future states-limiting their utility in tasks like autonomous navigation and robotics. To address these limitatio...

### 36. [A] CaDGS: Modeling Inter-Gaussian Mutual Information for Dynamic Novel View Synthesis
**ACMMM 2025 | Yunlong Zhao; Xiaoheng Deng; Zhuohua Qiu; Feng Yang; Chang Xu; Shan You; Xian...**
Source: both
**AI Assessment**: 4DGS for dynamic novel view synthesis, relevant methodology.
> Dynamic novel view synthesis (NVS) aims to render time-varying scenes from arbitrary viewpoints, balancing rendering quality and computational efficiency. While recent 4D Gaussian Splatting approaches offer promising real-time performance, they fundamentally overlook critical interdependence between...

### 37. [A] Per-Gaussian Embedding-Based Deformation for Deformable 3D Gaussian Splatting
**ECCV 2024 | Jeongmin Bae; Seoha Kim; Youngsik Yun; Hahyun Lee; Gun Bang; Youngjung Uh**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/02361.pdf)
Source: embedding
**AI Assessment**: Per-Gaussian deformation for deformable 3DGS, core deformation technique.
> As 3D Gaussian Splatting (3DGS) provides fast and high-quality novel view synthesis, it is a natural extension to deform a canonical 3DGS to multiple frames. However, we find that previous works fail to accurately reconstruct dynamic scenes, especially 1) static parts moving along nearby dynamic par...

### 38. [A] DGS-LRM: Real-Time Deformable 3D Gaussian Reconstruction From Monocular Videos
**NeurIPS 2025 | Chieh Lin; Zhaoyang Lv; Songyin Wu; Zhen Xu; Thu Nguyen-Phuoc; Hung-Yu Tseng;...**
[Paper](https://neurips.cc/virtual/2025/poster/117552)
Source: embedding
**AI Assessment**: Deformable GS reconstruction from monocular video, feed-forward method.
> We introduce the Deformable Gaussian Splats Large Reconstruction Model (DGS-LRM), the first feed-forward method predicting deformable 3D Gaussian splats from a monocular posed video of any dynamic scene. Feed-forward scene reconstruction has gained significant attention for its ability to rapidly cr...

### 39. [A] SplatFlow: Self-Supervised Dynamic Gaussian Splatting in Neural Motion Flow Field for Autonomous Driving
**CVPR 2025 | Su Sun; Cheng Zhao; Zhuoyang Sun; Yingjie Victor Chen; Mei Chen**
[PDF](https://arxiv.org/pdf/2411.15482.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Sun_SplatFlow_Self-Supervised_Dynamic_Gaussian_Splatting_in_Neural_Motion_Flow_Field_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2411.15482)
Source: embedding
**AI Assessment**: Dynamic GS for autonomous driving, reconstruction-focused.
> Most existing Dynamic Gaussian Splatting methods for complex dynamic urban scenarios rely on accurate object-level supervision from expensive manual labeling, limiting their scalability in real-world applications. In this paper, we introduce SplatFlow, a Self-Supervised Dynamic Gaussian Splatting wi...

### 40. [A] Dynamic Gaussians Mesh: Consistent Mesh Reconstruction from Dynamic Scenes
**ICLR 2025 | Isabella Liu; Hao Su; Xiaolong Wang**
[Paper](https://iclr.cc/virtual/2025/poster/29972)
Source: embedding
**AI Assessment**: Dynamic Gaussians with mesh output, reconstruction not editing.
> Modern 3D engines and graphics pipelines require mesh as a memory-efficient representation, which allows efficient rendering, geometry processing, texture editing, and many other downstream operations. However, it is still highly difficult to obtain high-quality mesh in terms of detailed structure a...

### 41. [A] 4D Gaussian Splatting SLAM
**ICCV 2025 | Yanyan Li; Youxu Fang; Zunjie Zhu; Kunyi Li; Yong Ding; Federico Tombari**
[PDF](https://arxiv.org/pdf/2503.16710.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Li_4D_Gaussian_Splatting_SLAM_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2503.16710)
Source: both
**AI Assessment**: 4DGS for SLAM, shares core 4DGS methodology but focuses on localization/mapping.
> Simultaneously localizing camera poses and constructing Gaussian radiance fields in dynamic scenes establish a crucial bridge between 2D images and the 4D real world. Instead of removing dynamic objects as distractors and reconstructing only static environments, this paper proposes an efficient arch...

### 42. [A] HoliGS: Holistic Gaussian Splatting for Embodied View Synthesis
**NeurIPS 2025 | Xiaoyuan Wang; Yizhou Zhao; Botao Ye; Shan Xiaojun; Weijie Lyu; Lu Qi; Kelvin...**
[Paper](https://neurips.cc/virtual/2025/poster/117722)
Source: both
**AI Assessment**: Deformable/4D GS for dynamic scenes with hierarchical decomposition. Relevant 4DGS technique.
> We propose HoliGS, a novel deformable Gaussian splatting framework that addresses embodied view synthesis from long monocular RGB videos. Unlike prior 4D Gaussian splatting and dynamic NeRF pipelines, which struggle with training overhead in minute-long captures, our method leverages invertible Gaus...

### 43. [A] Swift4D: Adaptive divide-and-conquer Gaussian Splatting for compact and efficient reconstruction of dynamic scene
**ICLR 2025 | Jiahao Wu; Rui Peng; Zhiyan Wang; Lu Xiao; Luyang Tang; Jinbo Yan; Kaiqiang X...**
[Paper](https://iclr.cc/virtual/2025/poster/29075)
Source: embedding
**AI Assessment**: 4DGS for compact/efficient dynamic reconstruction.
> Novel view synthesis has long been a practical but challenging task, although the introduction of numerous methods to solve this problem, even combining advanced representations like 3D Gaussian Splatting, they still struggle to recover high-quality results and often consume too much storage memory ...

### 44. [A] TrackerSplat: Exploiting Point Tracking for Fast and Robust Dynamic 3D Gaussians Reconstruction
**SIGGRAPH_Asia 2025 | Daheng Yin; Isaac Ding; Yili Jin; Jianxin Shi; Jiangchuan Liu**
[PDF](https://arxiv.org/pdf/2604.02586.pdf) | [Paper](https://doi.org/10.1145/3757377.3763829) | [arXiv](https://arxiv.org/abs/2604.02586)
Source: embedding
**AI Assessment**: Dynamic 3DGS reconstruction with point tracking.
> Recent advancements in 3D Gaussian Splatting (3DGS) have demonstrated its potential for efficient and photorealistic 3D reconstructions, which is crucial for diverse applications such as robotics and immersive media. However, current Gaussian-based methods for dynamic scene reconstruction struggle w...

### 45. [A] Neural Texture Splatting: Expressive 3D Gaussian Splatting for View Synthesis, Geometry, and Dynamic Reconstruction
**SIGGRAPH_Asia 2025 | Yiming Wang; Shaofei Wang; Marko Mihajlovic; Siyu Tang**
[PDF](https://arxiv.org/pdf/2511.18873.pdf) | [Paper](https://doi.org/10.1145/3757377.3763957) | [arXiv](https://arxiv.org/abs/2511.18873)
Source: embedding
**AI Assessment**: 3DGS extended to 4D/dynamic reconstruction, view synthesis.
> 3D Gaussian Splatting (3DGS) has emerged as a leading approach for high-quality novel view synthesis, with numerous variants extending its applicability to a broad spectrum of 3D and 4D scene reconstruction tasks. Despite its success, the representational capacity of 3DGS remains limited by the use ...

### 46. [A] GaussianUpdate: Continual 3D Gaussian Splatting Update for Changing Environments
**ICCV 2025 | Lin Zeng; Boming Zhao; Jiarui Hu; Xujie Shen; Ziqiang Dang; Hujun Bao; Zhaope...**
[PDF](https://arxiv.org/pdf/2508.08867.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Zeng_GaussianUpdate_Continual_3D_Gaussian_Splatting_Update_for_Changing_Environments_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2508.08867)
Source: embedding
**AI Assessment**: Continual 3DGS update for changing environments.
> Novel view synthesis with neural models has advanced rapidly in recent years, yet adapting these models to scene changes remains an open problem. Existing methods are either labor-intensive, requiring extensive model retraining, or fail to capture detailed types of changes over time. In this paper, ...

### 47. [A] STAG4D: Spatial-Temporal Anchored Generative 4D Gaussians
**ECCV 2024 | Yifei Zeng; Yanqin Jiang; Siyu Zhu; Yuanxun Lu; Youtian Lin; Hao Zhu; Weiming...**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/05288.pdf)
Source: embedding
**AI Assessment**: 4DGS for dynamic scene generation, relevant 4DGS technique.
> Recent progress in pre-trained diffusion models and 3D generation have spurred interest in 4D content creation. However, achieving high-fidelity 4D generation with spatial-temporal consistency remains a challenge. In this work, we propose STAG4D, a novel framework that combines pre-trained diffusion...

### 48. [A] MEGA: Memory-Efficient 4D Gaussian Splatting for Dynamic Scenes
**ICCV 2025 | Xinjie Zhang; Zhening Liu; Yifan Zhang; Xingtong Ge; Dailan He; Tongda Xu; Ya...**
[PDF](https://arxiv.org/pdf/2410.13613.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Zhang_MEGA_Memory-Efficient_4D_Gaussian_Splatting_for_Dynamic_Scenes_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2410.13613)
Source: keyword
**AI Assessment**: Memory-efficient 4DGS for dynamic scenes, methodological overlap.
> 4D Gaussian Splatting (4DGS) has recently emerged as a promising technique for capturing complex dynamic 3D scenes with high fidelity. It utilizes a 4D Gaussian representation and a GPU-friendly rasterizer, enabling rapid rendering speeds. Despite its advantages, 4DGS faces significant challenges, n...

### 49. [A] Clustered Error Correction with Grouped 4D Gaussian Splatting
**SIGGRAPH_Asia 2025 | Taeho Kang; Jaeyeon Park; Kyungjin Lee; Youngki Lee**
[PDF](https://arxiv.org/pdf/2511.16112.pdf) | [Paper](https://doi.org/10.1145/3757377.3763858) | [arXiv](https://arxiv.org/abs/2511.16112)
Source: keyword
**AI Assessment**: 4DGS for dynamic scene reconstruction with error correction, not editing.
> Existing 4D Gaussian Splatting (4DGS) methods struggle to accurately reconstruct dynamic scenes, often failing to resolve ambiguous pixel correspondences and inadequate densification in dynamic regions. We address these issues by introducing a novel method composed of two key components: (1) Ellipti...

### 50. [A] E-4DGS: High-Fidelity Dynamic Reconstruction from the Multi-view Event Cameras
**ACMMM 2025 | Chaoran Feng; Zhenyu Tang; Wangbo Yu; Yatian Pang; Yian Zhao; Jianbin Zhao; L...**
Source: keyword
**AI Assessment**: 4DGS for dynamic reconstruction with event cameras, not editing.
> Novel view synthesis and 4D reconstruction techniques predominantly rely on RGB cameras, thereby inheriting inherent limitations such as the dependence on adequate lighting, susceptibility to motion blur, and a limited dynamic range. Event cameras, offering advantages of low power, high temporal res...

### 51. [A] See Through the Occlusions: Amodal Gaussian Splatting for Few-Shot 3D Reconstruction
**ACMMM 2025 | Gwonjung Kim; Duyeol Lee; Jaehong Yang; Chae Eun Rhee**
Source: keyword
**AI Assessment**: Reinterprets time as deformation axis with opacity modulation, shares core 4DGS machinery.
> High-quality three-dimensional (3D) reconstruction from sparse views is critical for applications such as virtual and augmented reality, robotics, and digital content creation. While methods like Neural Radiance Fields (NeRF) and 3D Gaussian Splatting (3DGS) have shown strong performance in novel vi...

### 52. [A] DriveDreamer4D: World Models Are Effective Data Machines for 4D Driving Scene Representation
**CVPR 2025 | Guosheng Zhao; Chaojun Ni; Xiaofeng Wang; Zheng Zhu; Xueyang Zhang; Yida Wang...**
[PDF](https://arxiv.org/pdf/2410.13571.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Zhao_DriveDreamer4D_World_Models_Are_Effective_Data_Machines_for_4D_Driving_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2410.13571)
Source: keyword
**AI Assessment**: 4D driving scene representation using GS, but focused on driving simulation not editing.
> Closed-loop simulation is essential for advancing end-to-end autonomous driving systems. Contemporary sensor simulation methods, such as NeRF and 3DGS, rely predominantly on conditions closely aligned with training data distributions, which are largely confined to forward-driving scenarios. Conseque...

### 53. [A] GIFStream: 4D Gaussian-based Immersive Video with Feature Stream
**CVPR 2025 | Hao Li; Sicheng Li; Xiang Gao; Abudouaihati Batuer; Lu Yu; Yiyi Liao**
[PDF](https://arxiv.org/pdf/2505.07539.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Li_GIFStream_4D_Gaussian-based_Immersive_Video_with_Feature_Stream_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2505.07539)
Source: keyword
**AI Assessment**: 4DGS for immersive video, relevant 4DGS method but not editing.
> Immersive video offers a 6-Dof-Free viewing experience, potentially playing a key role in future video technology. Recently, 4D Gaussian Splatting has gained attention as an effective approach for immersive video due to its high rendering efficiency and quality, though maintaining quality with manag...

### 54. [A] HiMoR: Monocular Deformable Gaussian Reconstruction with Hierarchical Motion Representation
**CVPR 2025 | Yiming Liang; Tianhan Xu; Yuta Kikuchi**
[PDF](https://arxiv.org/pdf/2504.06210.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Liang_HiMoR_Monocular_Deformable_Gaussian_Reconstruction_with_Hierarchical_Motion_Representation_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2504.06210)
Source: keyword
**AI Assessment**: Deformable GS for dynamic reconstruction with hierarchical motion, core 4DGS method.
> We present Hierarchical Motion Representation (HiMoR), a novel deformation representation for 3D Gaussian primitives capable of achieving high-quality monocular dynamic 3D reconstruction. The insight behind HiMoR is that motions in everyday scenes can be decomposed into coarser motions that serve as...

### 55. [A] NTR-Gaussian: Nighttime Dynamic Thermal Reconstruction with 4D Gaussian Splatting Based on Thermodynamics
**CVPR 2025 | Kun Yang; Yuxiang Liu; Zeyu Cui; Yu Liu; Maojun Zhang; Shen Yan; Qing Wang**
[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/Yang_NTR-Gaussian_Nighttime_Dynamic_Thermal_Reconstruction_with_4D_Gaussian_Splatting_Based_CVPR_2025_paper.pdf)
Source: keyword
**AI Assessment**: 4DGS for dynamic thermal reconstruction, core 4DGS method.
> Thermal infrared imaging enables a non-invasive measurement of the surface temperature of objects with all-weather applicability. Leveraging such techniques for 3D reconstruction can accurately reflect the temperature distribution of a scene, thereby supporting applications such as building monitori...

### 56. [A] Robust Multi-Object 4D Generation for In-the-wild Videos
**CVPR 2025 | Wen-Hsuan Chu; Lei Ke; Jianmeng Liu; Mingxiao Huo; Pavel Tokmakov; Katerina F...**
[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/Chu_Robust_Multi-Object_4D_Generation_for_In-the-wild_Videos_CVPR_2025_paper.pdf)
Source: keyword
**AI Assessment**: Deformable 4DGS for dynamic scene generation from video, relevant 4DGS technique.
> We address the challenge of generating dynamic 4D scenes from monocular multi-object videos with heavy occlusions and introduce Robust4DGen, a novel approach that integrates rendering-based deformable 3D Gaussian optimization with generative priors for view synthesis. While existing view-synthesis m...

### 57. [A] 7DGS: Unified Spatial-Temporal-Angular Gaussian Splatting
**ICCV 2025 | Zhongpai Gao; Benjamin Planche; Meng Zheng; Anwesa Choudhuri; Terrence Chen; ...**
[PDF](https://arxiv.org/pdf/2503.07946.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Gao_7DGS_Unified_Spatial-Temporal-Angular_Gaussian_Splatting_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2503.07946)
Source: keyword
**AI Assessment**: Extends 4DGS by unifying spatial-temporal-angular dimensions, rendering-focused.
> Real-time rendering of dynamic scenes with view-dependent effects remains a fundamental challenge in computer graphics. While recent advances in Gaussian Splatting have shown promising results separately handling dynamic scenes (4DGS) and view-dependent effects (6DGS), no existing method unifies the...

### 58. [A] EMD: Explicit Motion Modeling for High-Quality Street Gaussian Splatting
**ICCV 2025 | Xiaobao Wei; Qingpo Wuwu; Zhongyu Zhao; Zhuangzhe Wu; Nan Huang; Ming Lu; Nin...**
[PDF](https://arxiv.org/pdf/2411.15582.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Wei_EMD_Explicit_Motion_Modeling_for_High-Quality_Street_Gaussian_Splatting_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2411.15582)
Source: keyword
**AI Assessment**: 4DGS for dynamic street scenes with explicit motion, reconstruction-focused.
> Photorealistic reconstruction of street scenes is essential for developing real-world simulators in autonomous driving. While recent methods based on 3D/4D Gaussian Splatting (GS) have demonstrated promising results, they still encounter challenges in complex street scenes due to the unpredictable m...

### 59. [A] LocalDyGS: Multi-view Global Dynamic Scene Modeling via Adaptive Local Implicit Feature Decoupling
**ICCV 2025 | Jiahao Wu; Rui Peng; Jianbo Jiao; Jiayu Yang; Luyang Tang; Kaiqiang Xiong; Ji...**
[PDF](https://arxiv.org/pdf/2507.02363.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Wu_LocalDyGS_Multi-view_Global_Dynamic_Scene_Modeling_via_Adaptive_Local_Implicit_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2507.02363)
Source: keyword
**AI Assessment**: Dynamic GS for multi-view dynamic scene modeling, core 4DGS method.
> Due to the complex and highly dynamic motions in the real world, synthesizing dynamic videos from multi-view inputs for arbitrary viewpoints is challenging. Previous works based on neural radiance field or 3D Gaussian splatting are limited to modeling fine-scale motion, greatly restricting their app...

## Grade B

### 60. [B] CoDa-4DGS: Dynamic Gaussian Splatting with Context and Deformation Awareness for Autonomous Driving
**ICCV 2025 | Rui Song; Chenwei Liang; Yan Xia; Walter Zimmer; Hu Cao; Holger Caesar; Andre...**
[PDF](https://openaccess.thecvf.com/content/ICCV2025/papers/Song_CoDa-4DGS_Dynamic_Gaussian_Splatting_with_Context_and_Deformation_Awareness_for_ICCV_2025_paper.pdf)
Source: both
**AI Assessment**: 4DGS for autonomous driving rendering, not editing/manipulation.
> Dynamic scene rendering opens new avenues in autonomous driving by enabling closed-loop simulations with photorealistic data, which is crucial for validating end-to-end algorithms. However, the complex and highly dynamic nature of traffic environments presents significant challenges in accurately re...

### 61. [B] DGNS: Deformable Gaussian Splatting and Dynamic Neural Surface for Monocular Dynamic 3D Reconstruction
**ACMMM 2025 | Xuesong Li; Jinguang Tong; Jie Hong; Vivien Rolland; Lars Petersson**
Source: both
**AI Assessment**: Deformable GS for reconstruction, not editing/manipulation.
> Dynamic scene reconstruction from monocular video is essential for real-world applications. We introduce DGNS, a hybrid framework integrating \underline{D}eformable \underline{G}aussian Splatting and Dynamic \underline{N}eural \underline{S}urfaces, effectively addressing dynamic novel-view synthesis...

### 62. [B] VoxelSplat: Dynamic Gaussian Splatting as an Effective Loss for Occupancy and Flow Prediction
**CVPR 2025 | Ziyue Zhu; Shenlong Wang; Jin Xie; Jiang-jiang Liu; Jingdong Wang; Jian Yang**
[PDF](https://arxiv.org/pdf/2506.05563.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Zhu_VoxelSplat_Dynamic_Gaussian_Splatting_as_an_Effective_Loss_for_Occupancy_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2506.05563)
Source: embedding
**AI Assessment**: Dynamic GS as loss for occupancy/flow prediction, tangential.
> Recent advancements in camera-based occupancy prediction have focused on the simultaneous prediction of 3D semantics and scene flow, a task that presents significant challenges due to specific difficulties, e.g., occlusions and unbalanced dynamic environments. In this paper, we analyze these challen...

### 63. [B] NeuroGauss4D-PCI: 4D Neural Fields and Gaussian Deformation Fields for Point Cloud Interpolation
**NeurIPS 2024 | Chaokang Jiang; Dalong Du; Jiuming Liu; Siting Zhu; Zhenqiang Liu; Zhuang Ma;...**
[Paper](https://neurips.cc/virtual/2024/poster/95602)
Source: embedding
**AI Assessment**: 4D neural fields for point cloud interpolation, not GS editing.
> Point Cloud Interpolation confronts challenges from point sparsity, complex spatiotemporal dynamics, and the difficulty of deriving complete 3D point clouds from sparse temporal information. This paper presents NeuroGauss4D-PCI, which excels at modeling complex non-rigid deformations across varied d...

### 64. [B] GSV3D: Gaussian Splatting-based Geometric Distillation with Stable Video Diffusion for Single-Image 3D Object Generation
**ICCV 2025 | Ye Tao; Jiawei Zhang; Yahao Shi; Dongqing Zou; Bin Zhou**
[PDF](https://arxiv.org/pdf/2503.06136.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Tao_GSV3D_Gaussian_Splatting-based_Geometric_Distillation_with_Stable_Video_Diffusion_for_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2503.06136)
Source: embedding
**AI Assessment**: 3DGS for single-image 3D generation, not dynamic/4D editing.
> Image-based 3D generation has vast applications in robotics and gaming, where high-quality, diverse outputs and consistent 3D representations are crucial. However, existing methods have limitations: 3D diffusion models are limited by dataset scarcity and the absence of strong pre-trained priors, whi...

### 65. [B] 1000+ FPS 4D Gaussian Splatting for Dynamic Scene Rendering
**NeurIPS 2025 | Yuheng Yuan; Qiuhong Shen; Xingyi Yang; Xinchao Wang**
[Paper](https://neurips.cc/virtual/2025/poster/117408)
Source: both
**AI Assessment**: Focuses on rendering speed optimization for 4DGS, not editing.
> 4D Gaussian Splatting (4DGS) has recently gained considerable attention as a method for reconstructing dynamic scenes. Despite achieving superior quality, 4DGS typically requires substantial storage and suffers from slow rendering speed. In this work, we delve into these issues and identify two key ...

### 66. [B] Generative Gaussian Splatting: Generating 3D Scenes with Video Diffusion Priors
**ICCV 2025 | Katja Schwarz; Norman Müller; Peter Kontschieder**
[PDF](https://openaccess.thecvf.com/content/ICCV2025/papers/Schwarz_Generative_Gaussian_Splatting_Generating_3D_Scenes_with_Video_Diffusion_Priors_ICCV_2025_paper.pdf)
Source: embedding
**AI Assessment**: GS with generative priors for static scene synthesis.
> Synthesizing consistent and photorealistic 3D scenes is an open problem in computer vision. Video diffusion models generate impressive videos but cannot directly synthesize 3D representations, i.e., lack 3D consistency in the generated sequences. In addition, directly training generative 3D models i...

### 67. [B] RobustSplat: Decoupling Densification and Dynamics for Transient-Free 3DGS
**ICCV 2025 | Chuanyu Fu; Yuqi Zhang; Kunbin Yao; Guanying Chen; Yuan Xiong; Chuan Huang; S...**
[PDF](https://arxiv.org/pdf/2506.02751.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Fu_RobustSplat_Decoupling_Densification_and_Dynamics_for_Transient-Free_3DGS_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2506.02751)
Source: embedding
**AI Assessment**: Robustness of 3DGS in dynamic scenes, transient removal.
> 3D Gaussian Splatting (3DGS) has gained significant attention for its real-time, photo-realistic rendering in novel-view synthesis and 3D modeling. However, existing methods struggle with accurately modeling scenes affected by transient objects, leading to artifacts in the rendered images. We identi...

### 68. [B] Spike4DGS: Towards High-Speed Dynamic Scene Rendering with 4D Gaussian Splatting via a Spike Camera Array
**NeurIPS 2025 | Qinghong Ye; Yiqian Chang; Jianing Li; Haoran Xu; Xuan Wang; Wei Zhang; Yongh...**
[Paper](https://neurips.cc/virtual/2025/poster/117721)
Source: keyword
**AI Assessment**: 4DGS with spike cameras, specialized sensor input not editing.
> Spike camera with high temporal resolution offers a new perspective on high-speed dynamic scene rendering. Most existing rendering methods rely on Neural Radiance Fields (NeRF) or 3D Gaussian Splatting (3DGS) for static scenes using a monocular spike camera. However, these methods struggle with dyna...

### 69. [B] Temporal Smoothness-Aware Rate-Distortion Optimized 4D Gaussian Splatting
**NeurIPS 2025 | Hyeongmin Lee; Kyungjune Baek**
[Paper](https://neurips.cc/virtual/2025/poster/115526)
Source: keyword
**AI Assessment**: 4DGS compression/storage efficiency, not editing.
> Dynamic 4D Gaussian Splatting (4DGS) effectively extends the high-speed rendering capabilities of 3D Gaussian Splatting (3DGS) to represent volumetric videos. However, the large number of Gaussians, substantial temporal redundancies, and especially the absence of an entropy-aware compression framewo...

### 70. [B] Virtually Being: Customizing Camera-Controllable Video Diffusion Models with Volumetric Performance Captures
**SIGGRAPH_Asia 2025 | Yuancheng Xu; Wenqi Xian; Li Ma; Julien Philip; Ahmet Tasel; Yiwei Zhao; Ryan...**
[Paper](https://doi.org/10.1145/3757377.3763888)
Source: keyword
**AI Assessment**: 4DGS as data source for video diffusion, not editing.
> We introduce a framework that enables both multi-view character consistency and 3D camera control in video diffusion models through a novel customization data pipeline. We train the character consistency component with recorded volumetric capture performances re-rendered with diverse camera trajecto...

### 71. [B] HoloTime: Taming Video Diffusion Models for Panoramic 4D Scene Generation
**ACMMM 2025 | Haiyang Zhou; Wangbo Yu; Jiawen Guan; Xinhua Cheng; Yonghong Tian; Li Yuan**
Source: keyword
**AI Assessment**: Panoramic 4D scene generation, not editing.
> The rapid advancement of diffusion models holds the promise of revolutionizing the application of VR and AR technologies, which typically require scene-level 4D assets for user experience. Nonetheless, existing diffusion models predominantly concentrate on modeling static 3D scenes or object-level d...

### 72. [B] AniGS: Animatable Gaussian Avatar from a Single Image with Inconsistent Gaussian Reconstruction
**CVPR 2025 | Lingteng Qiu; Shenhao Zhu; Qi Zuo; Xiaodong Gu; Yuan Dong; Junfei Zhang; Chao...**
[PDF](https://arxiv.org/pdf/2412.02684.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Qiu_AniGS_Animatable_Gaussian_Avatar_from_a_Single_Image_with_Inconsistent_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2412.02684)
Source: keyword
**AI Assessment**: Animatable avatar from single image, not scene editing.
> Generating animatable human avatars from a single image is essential for various digital human modeling applications. Existing 3D reconstruction methods often struggle to capture fine details in animatable models, while generative approaches for controllable animation, though avoiding explicit 3D mo...

### 73. [B] Generative Sparse-View Gaussian Splatting
**CVPR 2025 | Hanyang Kong; Xingyi Yang; Xinchao Wang**
[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/Kong_Generative_Sparse-View_Gaussian_Splatting_CVPR_2025_paper.pdf)
Source: keyword
**AI Assessment**: Sparse-view 3DGS for novel view synthesis, not 4D or editing.
> Novel view synthesis from limited observations remains a significant challenge due to the lack of information in under-sampled regions, often resulting in noticeable artifacts. We introduce Generative Sparse-view Gaussian Splatting (GS-GS), a general pipeline designed to enhance the rendering qualit...

### 74. [B] Improving Gaussian Splatting with Localized Points Management
**CVPR 2025 | Haosen Yang; Chenhao Zhang; Wenqing Wang; Marco Volino; Adrian Hilton; Li Zha...**
[PDF](https://arxiv.org/pdf/2406.04251.pdf) | [Paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Yang_Improving_Gaussian_Splatting_with_Localized_Points_Management_CVPR_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2406.04251)
Source: keyword
**AI Assessment**: Improves 3DGS optimization, foundational but not 4D or editing.
> Point management is critical for optimizing 3D Gaussian Splatting models, as point initiation (e.g., via structure from motion) is often distributionally inappropriate. Typically, Adaptive Density Control (ADC) algorithm is adopted, leveraging view-averaged gradient magnitude thresholding for point ...

### 75. [B] InteractAvatar: Modeling Hand-Face Interaction in Photorealistic Avatars with Deformable Gaussians
**ICCV 2025 | Kefan Chen; Sreyas Mohan; Justin Theiss; Sergiu Oprea; Srinath Sridhar; Aayus...**
[PDF](https://arxiv.org/pdf/2504.07949.pdf) | [Paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Chen_InteractAvatar_Modeling_Hand-Face_Interaction_in_Photorealistic_Avatars_with_Deformable_Gaussians_ICCV_2025_paper.pdf) | [arXiv](https://arxiv.org/abs/2504.07949)
Source: keyword
**AI Assessment**: Deformable Gaussians for avatar modeling, avatar-specific not scene editing.
> With the rising interest from the community in digital avatars coupled with the importance of expressions and gestures in communication, modeling natural avatar behavior remains an important challenge across many industries such as teleconferencing, gaming, and AR/VR. Human hands are the primary too...

## Grade C

### 76. [C] Go-with-the-Flow: Motion-Controllable Video Diffusion Models Using Real-Time Warped Noise
**CVPR 2025 | Ryan Burgert; Yuancheng Xu; Wenqi Xian; Oliver Pilarski; Pascal Clausen; Ming...**
[PDF](https://openaccess.thecvf.com/content/CVPR2025/papers/Burgert_Go-with-the-Flow_Motion-Controllable_Video_Diffusion_Models_Using_Real-Time_Warped_Noise_CVPR_2025_paper.pdf)
Source: keyword
**AI Assessment**: Motion-controllable video diffusion, no GS or 3D/4D scene editing.
> Generative modeling aims to transform random noise into structured outputs. In this work, we enhance video diffusion models by allowing motion control via structured latent noise sampling. This is achieved by just a change in data: we pre-process training videos to yield structured noise. Consequent...

### 77. [C] Watching it in Dark: A Target-aware Representation Learning Framework for High-Level Vision Tasks in Low Illumination
**ECCV 2024 | Yunan LI; Yihao Zhang; Shoude Li; Long Tian; DOU QUAN; Chaoneng Li; Qiguang Miao**
[PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/09518.pdf)
Source: keyword
**AI Assessment**: Low-light vision, no connection to GS or 3D/4D editing.
> Low illumination significantly impacts the performance of learning-based models trained in well-lit conditions. Although current methods alleviate this issue through either image-level enhancement or feature-level adaptation, they often focus solely on the image itself, ignoring how the task-relevan...

### 78. [C] Mixture of Experts Guided by Gaussian Splatters Matters: A new Approach to Weakly-Supervised Video Anomaly Detection
**ICCV 2025 | Giacomo D' Amicantonio; Snehashis Majhi; Quan Kong; Lorenzo Garattoni; Gianpi...**
[PDF](https://openaccess.thecvf.com/content/ICCV2025/papers/Amicantonio_Mixture_of_Experts_Guided_by_Gaussian_Splatters_Matters_A_new_ICCV_2025_paper.pdf)
Source: keyword
**AI Assessment**: GS for video anomaly detection, unrelated to scene editing.
> Video Anomaly Detection (VAD) is a challenging task due to the variability of anomalous events and the limited availability of labeled data. Under the Weakly-Supervised VAD (WSVAD) paradigm, only video-level labels are provided during training, while predictions are made at the frame level. Although...

### 79. [C] An Exploration with Entropy Constrained 3D Gaussians for 2D Video Compression
**ICLR 2025 | Xiang Liu; Bin Chen; Zimo Liu; Yaowei Wang; Shu-Tao Xia**
[Paper](https://iclr.cc/virtual/2025/poster/30096)
Source: keyword
**AI Assessment**: 3DGS for video compression, peripheral application.
> 3D Gaussian Splatting (3DGS) has witnessed its rapid development in novel view synthesis, which attains high quality reconstruction and real-time rendering. At the same time, there is still a gap before implicit neural representation (INR) can become a practical compressor due to the lack of stream ...

### 80. [C] Bidirectional Temporal Diffusion Model for Temporally Consistent Human Animation
**ICLR 2024 | Tserendorj Adiya; Jae Shin Yoon; Jung Eun Lee; Sanghun Kim; Hwasup Lim**
[Paper](https://iclr.cc/virtual/2024/poster/17420)
Source: keyword
**AI Assessment**: Human animation via diffusion, no GS or 3D/4D editing.
> We introduce a method to generate temporally coherent human animation from a single image, a video, or a random noise.This problem has been formulated as modeling of an auto-regressive generation, i.e., to regress past frames to decode future frames.However, such unidirectional generation is highly ...

### 81. [C] Optimal Sensor Scheduling and Selection for Continuous-Discrete Kalman Filtering with Auxiliary Dynamics
**ICML 2025 | Mohamad Al Ahdab; john leth; Zheng-Hua Tan**
[Paper](https://icml.cc/virtual/2025/poster/46077)
Source: keyword
**AI Assessment**: Sensor scheduling for Kalman filtering, unrelated to GS.
> We study the Continuous-Discrete Kalman Filter (CD-KF) for State-Space Models (SSMs) where continuous-time dynamics are observed via multiple sensors with discrete, irregularly timed measurements. Our focus extends to scenarios in which the measurement process is coupled with the states of an auxili...

### 82. [C] Robust and Conjugate Spatio-Temporal Gaussian Processes
**ICML 2025 | William Laplante; Matias Altamirano; Andrew Duncan; Jeremias Knoblauch; Franc...**
[Paper](https://icml.cc/virtual/2025/poster/44920)
Source: keyword
**AI Assessment**: Gaussian process regression, unrelated to Gaussian Splatting.
> State-space formulations allow for Gaussian process (GP) regression with linear-in-time computational cost in spatio-temporal settings, but performance typically suffers in the presence of outliers. In this paper, we adapt and specialise the *robust and conjugate GP (RCGP)* framework of Altamirano e...
