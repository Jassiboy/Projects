package Demo.Main.Entity;

import Demo.Main.Resources;

import java.awt.*;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class Bird extends Entity {
    private Image[] birdImages = {Resources.birdImage1, Resources.birdImage2,};
    private int currentImageIndex = 0;

    public Bird(int xCord, int yCord) {
        super(xCord, yCord, 100, 92);
    }

    public void update() {
        super.update();
        currentImageIndex++;
        currentImageIndex %= 2;

    }

    @Override
    public Image getImage() {
        return birdImages[currentImageIndex];
    }
}
