tr timeout: 6m  
      aining/smol-vlm/training.log)   40s
  ⎿ =================================================     
    ===========
    SmolVLM-256M Fine-tuning for Ad Classification        
    … +50 lines (ctrl+o to expand)


● It's progressing past step 17 now (where it failed      
  before). The training is running successfully in the    
   background.

● Training is now running in the background!

  Summary

  Training is successfully running and will persist       
  even if you close this terminal or disconnect.

  Current progress: ~14/2295 steps (about 6 minutes
  in)

  Estimated time: ~17 hours for 3 epochs (at
  ~26s/step)

  Monitoring Commands

  # Watch live progress
  tail -f /home/ubuntu/training/smol-vlm/training.log     

  # Check if still running
  ps aux | grep train.py

  # Check GPU usage
  docker exec smolvlm-training nvidia-smi

  What's happening:

  - Dataset: 24,473 train / 2,720 val images (balanced    
   ads vs non-ads)
  - Model: SmolVLM-256M-Instruct with LoRA (2.2%
  trainable params)
  - Prompt: "Is this an ad?" → "Yes" / "No"
  - Steps: 2,295 total (3 epochs)

  After training completes:

  # Enter container
  docker exec -it smolvlm-training bash

  # Merge LoRA weights
  python /workspace/smol-vlm/merge_and_export.py

  # Test the model
  python /workspace/smol-vlm/test_model.py
  /workspace/data/pitt_ads/ads/0/10000.jpg

  The output will be saved to
  /workspace/smol-vlm/output/final/ (LoRA) and
  /workspace/smol-vlm/output/merged/ (full model).    